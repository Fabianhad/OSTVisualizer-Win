from typing import Protocol, runtime_checkable
from ..entities.file_state import FileState


@runtime_checkable
class IFileStateRepository(Protocol):
    def load(self) -> FileState: ...
    def save(self, file_state: FileState) -> None: ...
