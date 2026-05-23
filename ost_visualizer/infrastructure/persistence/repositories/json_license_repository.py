import logging
from pathlib import Path
from typing import Optional
from ....domain.entities.license import License
from ....domain.repositories.i_license_repository import ILicenseRepository
from ...app_paths import get_app_data_dir
from .json_repository_base import JsonRepositoryBase


class JsonLicenseRepository(JsonRepositoryBase, ILicenseRepository):
    def __init__(
        self,
        license_path: Optional[Path] = None,
        logger: Optional[logging.Logger] = None,
    ):
        path = license_path or (get_app_data_dir() / "license_cache.json")
        super().__init__(path, "license cache", logger)
        self.license_path = path

    def load(self) -> License:
        return License.from_dict(self._load_json())

    def save(self, license_data: License) -> None:
        self._save_json(license_data.to_dict())

    def clear(self) -> None:
        if self._file_path.exists():
            try:
                self._file_path.unlink()
            except OSError as exc:
                self.logger.error(
                    "Failed to delete license cache %s: %s", self._file_path, exc
                )
                raise
