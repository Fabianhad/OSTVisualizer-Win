import logging
import os
from typing import List, Optional, Tuple
from ....domain.entities.file_state import FileEntry
from ....domain.repositories.i_file_state_repository import IFileStateRepository


class CleanupDeletedFilesUseCase:
    def __init__(
        self,
        file_state_repository: IFileStateRepository,
        logger: Optional[logging.Logger] = None,
    ):
        self.file_state_repository = file_state_repository
        self.logger = logger or logging.getLogger(__name__)

    def execute(self, file_entries: List[FileEntry]) -> Tuple[List[FileEntry], int]:
        original_count = len(file_entries)
        cleaned_entries = [
            entry for entry in file_entries if os.path.exists(entry.file_path)
        ]
        removed_count = original_count - len(cleaned_entries)
        return cleaned_entries, removed_count

    def execute_and_save(self) -> int:
        try:
            file_state = self.file_state_repository.load()
        except (FileNotFoundError, OSError, ValueError) as exc:
            self.logger.warning("Could not load file state for cleanup: %s", exc)
            return 0
        if not file_state.file_entries:
            return 0
        original_count = len(file_state.file_entries)
        file_state.file_entries = [
            entry
            for entry in file_state.file_entries
            if os.path.exists(entry.file_path)
        ]
        removed_count = original_count - len(file_state.file_entries)
        if removed_count > 0:
            try:
                self.file_state_repository.save(file_state)
            except OSError as exc:
                self.logger.error("Failed to save file state after cleanup: %s", exc)
                return 0
        return removed_count
