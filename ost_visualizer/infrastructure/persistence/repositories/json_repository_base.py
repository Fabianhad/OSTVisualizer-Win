import json
import logging
from pathlib import Path
from typing import Optional


class JsonRepositoryBase:
    def __init__(
        self,
        file_path: Path,
        entity_name: str,
        logger: Optional[logging.Logger] = None,
    ) -> None:
        self.logger = logger or logging.getLogger(__name__)
        self._file_path = file_path
        self._entity_name = entity_name

    def _load_json(self) -> dict:
        if not self._file_path.exists():
            raise FileNotFoundError(self._file_path)
        try:
            with self._file_path.open("r", encoding="utf-8") as handle:
                return json.load(handle)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid JSON in {self._file_path}") from exc
        except OSError as exc:
            raise OSError(
                f"Unable to read {self._entity_name} {self._file_path}"
            ) from exc

    def _save_json(self, data: dict) -> None:
        try:
            self._file_path.parent.mkdir(parents=True, exist_ok=True)
            temp_path = self._file_path.with_suffix(self._file_path.suffix + ".tmp")
            with temp_path.open("w", encoding="utf-8") as handle:
                json.dump(data, handle, indent=2)
            temp_path.replace(self._file_path)
        except OSError as exc:
            self.logger.error(
                "Failed to save %s %s: %s", self._entity_name, self._file_path, exc
            )
            raise
