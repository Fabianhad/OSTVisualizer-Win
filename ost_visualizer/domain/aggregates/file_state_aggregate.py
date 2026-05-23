import logging
from typing import List, Optional
from ..entities.file_state import FileState, deduplicate_entries
from ..repositories.i_file_state_repository import IFileStateRepository


class FileStateAggregate:
    def __init__(
        self,
        repository: IFileStateRepository,
        logger: Optional[logging.Logger] = None,
    ):
        self.logger = logger or logging.getLogger(__name__)
        self.repository = repository
        self._state = FileState()
        self._load_state()

    def _load_state(self) -> None:
        try:
            self._state = self.repository.load()
        except FileNotFoundError:
            self._state = FileState()
        except ValueError as exc:
            self.logger.error("%s; starting with empty state", exc)
            self._state = FileState()
        except OSError as exc:
            self.logger.error("Error reading file state: %s", exc)
            self._state = FileState()
        except Exception as exc:
            self.logger.exception("Unexpected error loading file state: %s", exc)
            self._state = FileState()

    def _save_state(self) -> None:
        try:
            self.repository.save(self._state)
        except OSError as exc:
            self.logger.error("Error saving file state: %s", exc)
            raise
        except Exception as exc:
            self.logger.exception("Unexpected error saving file state: %s", exc)
            raise

    @property
    def file_entries(self) -> List:
        return list(self._state.file_entries)

    def get_checked_files(self) -> List[str]:
        return self._state.get_checked_files()

    def clear(self) -> None:
        self._state.clear()
        self._save_state()

    def update_entries(self, file_entries: List) -> None:
        self._state.file_entries = deduplicate_entries(file_entries)
        self._save_state()

    def contains_path(self, file_path: str) -> bool:
        return self._state.contains_path(file_path)

    def reload(self) -> None:
        self._load_state()
