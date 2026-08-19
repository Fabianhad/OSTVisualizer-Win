import json
import logging
import os
import uuid
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
        try:
            with self._file_path.open("r", encoding="utf-8") as handle:
                return json.load(handle)
        except FileNotFoundError:
            raise
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid JSON in {self._file_path}") from exc
        except OSError as exc:
            raise OSError(
                f"Unable to read {self._entity_name} {self._file_path}"
            ) from exc

    def _save_json(self, data: dict) -> None:
        temp_path = self._new_temp_path()
        try:
            self._file_path.parent.mkdir(parents=True, exist_ok=True)
            with temp_path.open("w", encoding="utf-8") as handle:
                json.dump(data, handle, indent=2)
                handle.flush()
                os.fsync(handle.fileno())
            temp_path.replace(self._file_path)
        except OSError as exc:
            self.logger.error(
                "Failed to save %s %s: %s", self._entity_name, self._file_path, exc
            )
            raise
        finally:
            try:
                temp_path.unlink(missing_ok=True)
            except OSError:
                pass

    def _save_json_if_absent(self, data: dict) -> bool:
        temp_path = self._new_temp_path()
        try:
            self._file_path.parent.mkdir(parents=True, exist_ok=True)
            with temp_path.open("x", encoding="utf-8") as handle:
                json.dump(data, handle, indent=2)
                handle.flush()
                os.fsync(handle.fileno())
            try:
                os.link(temp_path, self._file_path)
            except FileExistsError:
                return False
            return True
        except OSError as exc:
            self.logger.error(
                "Failed to initialize %s %s: %s",
                self._entity_name,
                self._file_path,
                exc,
            )
            raise
        finally:
            try:
                temp_path.unlink(missing_ok=True)
            except OSError:
                pass

    def _new_temp_path(self) -> Path:
        return self._file_path.with_name(
            f".{self._file_path.name}.{uuid.uuid4().hex}.tmp"
        )
