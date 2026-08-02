import logging
from pathlib import Path
from typing import Callable, Optional
from ..dtos.collaboration_dtos import ProjectImportPayload, QueuedMutationResult
from ..interfaces.i_osp_importer import IOspImporter
from ..interfaces.i_ost_importer import IOstImporter
from .base_write_service import BaseWriteService


class ImportService(BaseWriteService):
    def __init__(
        self,
        ost_importer: IOstImporter,
        osp_importer: IOspImporter,
        project_write_service,
        reload_database=None,
        event_bus=None,
        logger: Optional[logging.Logger] = None,
    ) -> None:
        super().__init__(reload_database, event_bus, logger)
        self._ost_importer = ost_importer
        self._osp_importer = osp_importer
        self._project_write_service = project_write_service

    def uses_sql_collaboration_import(self, database_id: str) -> bool:
        return self._project_write_service.uses_sql_collaboration_mutations(database_id)

    def queue_project_import(
        self,
        source_path: str,
        source_kind: str,
        target_db_path: str,
        target_project_uid: Optional[str],
        callback: Callable[[QueuedMutationResult], None],
    ) -> int:
        source = Path(source_path)
        stat = source.stat()
        payload = ProjectImportPayload(
            source_path=str(source),
            source_kind=source_kind,
            source_size=stat.st_size,
            source_modified_ns=stat.st_mtime_ns,
            target_project_uid=str(target_project_uid or ""),
        )

        def import_work(recorder):
            current = source.stat()
            if (
                current.st_size != payload.source_size
                or current.st_mtime_ns != payload.source_modified_ns
            ):
                raise RuntimeError(
                    "The import source changed after the operation was queued."
                )
            if payload.source_kind == "ost":
                return self._ost_importer.import_ost_mutation(
                    str(source),
                    target_db_path,
                    payload.target_project_uid or None,
                    recorder,
                )
            return self._osp_importer.import_osp_mutation(
                str(source),
                target_db_path,
                payload.target_project_uid or None,
                recorder,
            )

        return self._project_write_service.queue_project_import(
            target_db_path,
            target_project_uid,
            payload,
            import_work,
            callback,
        )

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
