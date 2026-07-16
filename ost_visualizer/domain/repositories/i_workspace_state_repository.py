from pathlib import Path
from typing import Protocol
from ..entities.workspace_state import WorkspaceState


class IWorkspaceStateRepository(Protocol):
    workspace_state_path: Path

    def load(self) -> WorkspaceState: ...
    def save(self, workspace_state: WorkspaceState) -> None: ...
