import logging
from pathlib import Path
from typing import Optional
from ....domain.entities.workspace_state import WorkspaceState
from ....domain.repositories.i_workspace_state_repository import (
    IWorkspaceStateRepository,
)
from ...app_paths import get_app_data_dir
from .json_repository_base import JsonRepositoryBase


class JsonWorkspaceStateRepository(JsonRepositoryBase, IWorkspaceStateRepository):
    def __init__(
        self,
        workspace_state_path: Optional[Path] = None,
        logger: Optional[logging.Logger] = None,
    ):
        path = workspace_state_path or (get_app_data_dir() / "workspace_state.json")
        super().__init__(path, "workspace state", logger)
        self.workspace_state_path = path

    def load(self) -> WorkspaceState:
        return WorkspaceState.from_dict(self._load_json())

    def save(self, workspace_state: WorkspaceState) -> None:
        self._save_json(workspace_state.to_dict())
