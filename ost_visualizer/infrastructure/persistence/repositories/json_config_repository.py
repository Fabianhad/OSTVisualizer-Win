import logging
from pathlib import Path
from typing import Optional
from ....domain.entities.config import Config
from ....domain.repositories.i_config_repository import IConfigRepository
from ...app_paths import get_app_data_dir
from .json_repository_base import JsonRepositoryBase


class JsonConfigRepository(JsonRepositoryBase, IConfigRepository):
    def __init__(
        self,
        config_path: Optional[Path] = None,
        logger: Optional[logging.Logger] = None,
    ):
        path = config_path or (get_app_data_dir() / "config.json")
        super().__init__(path, "configuration", logger)
        self.config_path = path

    def load(self) -> Config:
        return Config.from_dict(self._load_json())

    def save(self, config: Config) -> None:
        self._save_json(config.to_dict())
