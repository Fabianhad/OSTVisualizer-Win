import logging
import os
from typing import List, Optional
from ....domain.entities.database_descriptor import DatabaseBackend
from ....domain.repositories.i_file_state_repository import IFileStateRepository
from .load_file_use_case import LoadFileUseCase


class LoadFilesFromConfigUseCase:
    def __init__(
        self,
        load_file_use_case: LoadFileUseCase,
        file_state_repository: IFileStateRepository,
        logger: Optional[logging.Logger] = None,
    ):
        self.load_file_use_case = load_file_use_case
        self.file_state_repository = file_state_repository
        self.logger = logger or logging.getLogger(__name__)

    def execute(self, backends: set[DatabaseBackend]) -> List[str]:
        try:
            file_state = self.file_state_repository.load()
        except FileNotFoundError:
            return []
        except (OSError, ValueError) as exc:
            self.logger.warning("Could not load file state from config: %s", exc)
            return []
        if not file_state.file_entries:
            return []
        entries_to_load = [
            entry
            for entry in file_state.file_entries
            if entry.is_checked and entry.backend in backends
        ]
        if not entries_to_load:
            return []
        successfully_loaded = []
        for entry in entries_to_load:
            locator = entry.runtime_locator
            if entry.backend == DatabaseBackend.ACCESS and not os.path.exists(
                entry.file_path
            ):
                self.logger.warning("File not found, skipping: %s", entry.file_path)
                continue
            try:
                success = self.load_file_use_case.execute(locator)
                if success:
                    successfully_loaded.append(locator)
            except Exception as exc:
                self.logger.exception("Error loading database %s: %s", locator, exc)
        return successfully_loaded
