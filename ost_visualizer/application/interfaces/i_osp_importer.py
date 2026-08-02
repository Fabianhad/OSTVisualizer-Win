from typing import Optional, Protocol


class IOspImporter(Protocol):
    def import_osp(
        self,
        osp_file_path: str,
        target_db_path: str,
        target_project_uid: Optional[str] = None,
    ) -> bool: ...
    def import_osp_mutation(
        self,
        osp_file_path: str,
        target_db_path: str,
        target_project_uid: Optional[str],
        recorder,
    ) -> dict[str, object]: ...
