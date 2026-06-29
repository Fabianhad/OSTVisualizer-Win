import logging
from datetime import datetime
from pathlib import Path
from typing import Callable, List, Optional
from ...domain.entities.file_state import FileEntry, normalize_path
from ..interfaces.i_database_creator import IDatabaseCreator


class WorkingDirectoryService:
    def __init__(
        self,
        database_creator: IDatabaseCreator,
        working_dir: Path,
        logger: Optional[logging.Logger] = None,
    ) -> None:
        self._database_creator = database_creator
        self._logger = logger or logging.getLogger(__name__)
        self._working_dir = working_dir

    @property
    def working_dir(self) -> Path:
        return self._working_dir

    def ensure_working_dir(self) -> None:
        self._working_dir.mkdir(parents=True, exist_ok=True)

    def discover_databases(self) -> List[Path]:
        if not self._working_dir.exists():
            return []
        return sorted(self._working_dir.glob("*.mdb"))

    def merge_discovered_into_file_state(
        self, existing_entries: List[FileEntry]
    ) -> List[FileEntry]:
        discovered = self.discover_databases()
        if not discovered:
            return existing_entries
        known_paths = {normalize_path(e.file_path) for e in existing_entries}
        merged = list(existing_entries)
        for db_path in discovered:
            norm = normalize_path(str(db_path))
            if norm not in known_paths:
                merged.append(FileEntry(file_path=str(db_path), is_checked=True))
        return merged

    def create_database(
        self,
        name: Optional[str] = None,
        progress_callback: Optional[Callable[[str], None]] = None,
    ) -> Optional[Path]:
        self.ensure_working_dir()
        if not name:
            name = self._generate_default_name()
        file_name = f"{name}.mdb"
        db_path = self._working_dir / file_name
        if db_path.exists():
            self._logger.info("Database already exists: %s", db_path)
            return None
        success = self._database_creator.create_database(
            db_path,
            name,
            progress_callback=progress_callback,
        )
        return db_path if success else None

    def _generate_default_name(self) -> str:
        return datetime.now().strftime("%#m-%#d-%Y %#H-%#M-%#S")
