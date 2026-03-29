import logging
from pathlib import Path
from typing import Optional
from ....domain.entities.file_state import FileState
from ....domain.repositories.i_file_state_repository import IFileStateRepository
from ...app_paths import get_app_data_dir
from .json_repository_base import JsonRepositoryBase


class JsonFileStateRepository(JsonRepositoryBase, IFileStateRepository):
    def __init__(
        self,
        file_state_path: Optional[Path] = None,
        logger: Optional[logging.Logger] = None,
    ):
        path = file_state_path or (get_app_data_dir() / "file_state.json")
        super().__init__(path, "file state", logger)
        self.file_state_path = path

    def load(self) -> FileState:
        return FileState.from_dict(self._load_json())

    def save(self, file_state: FileState) -> None:
        self._save_json(file_state.to_dict())
