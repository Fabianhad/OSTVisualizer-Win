import logging
from typing import List, Optional
from ..entities.file_state import FileEntry, FileState, deduplicate_entries
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

    def _save_state(self, state: FileState) -> None:
        try:
            self.repository.save(state)
        except OSError as exc:
            self.logger.error("Error saving file state: %s", exc)
            raise

    @property
    def file_entries(self) -> List[FileEntry]:
        return [
            entry.with_checked(entry.is_checked) for entry in self._state.file_entries
        ]

    def update_entries(self, file_entries: List[FileEntry]) -> None:
        state = FileState(
            file_entries=[
                entry.with_checked(entry.is_checked)
                for entry in deduplicate_entries(file_entries)
            ]
        )
        self._save_state(state)
        self._state = state

    def contains_path(self, file_path: str) -> bool:
        return self._state.contains_path(file_path)

    def reload(self) -> None:
        self._load_state()
