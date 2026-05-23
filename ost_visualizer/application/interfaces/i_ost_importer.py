from typing import Optional, Protocol


class IOstImporter(Protocol):
    def import_ost(
        self,
        ost_file_path: str,
        target_db_path: str,
        target_project_uid: Optional[str] = None,
    ) -> bool: ...
