import logging
import os
from typing import List, Optional
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

    def execute(self) -> List[str]:
        try:
            file_state = self.file_state_repository.load()
        except Exception:
            return []
        if not file_state.file_entries:
            return []
        files_to_load = [
            entry.file_path for entry in file_state.file_entries if entry.is_checked
        ]
        if not files_to_load:
            return []
        successfully_loaded = []
        failed_files = []
        for file_path in files_to_load:
            if not os.path.exists(file_path):
                self.logger.warning("File not found, skipping: %s", file_path)
                failed_files.append(file_path)
                continue
            try:
                success = self.load_file_use_case.execute(file_path)
                if success:
                    successfully_loaded.append(file_path)
                else:
                    self.logger.warning("Failed to load file: %s", file_path)
                    failed_files.append(file_path)
            except Exception as exc:
                self.logger.exception("Error loading file %s: %s", file_path, exc)
                failed_files.append(file_path)
        return successfully_loaded
