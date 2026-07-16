from typing import Protocol
from ..entities.file_state import FileState


class IFileStateRepository(Protocol):
    def load(self) -> FileState: ...
    def save(self, file_state: FileState) -> None: ...
