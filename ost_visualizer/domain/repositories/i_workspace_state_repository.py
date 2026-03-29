from pathlib import Path
from typing import Protocol, runtime_checkable
from ..entities.workspace_state import WorkspaceState


@runtime_checkable
class IWorkspaceStateRepository(Protocol):
    workspace_state_path: Path

    def load(self) -> WorkspaceState: ...
    def save(self, workspace_state: WorkspaceState) -> None: ...
