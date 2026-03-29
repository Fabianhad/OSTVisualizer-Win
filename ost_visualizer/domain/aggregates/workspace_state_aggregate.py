import logging
from copy import deepcopy
from typing import Optional
from ..entities.workspace_state import WorkspaceState
from ..repositories.i_workspace_state_repository import IWorkspaceStateRepository


class WorkspaceStateAggregate:
    def __init__(
        self,
        repository: IWorkspaceStateRepository,
        logger: Optional[logging.Logger] = None,
    ):
        self.logger = logger or logging.getLogger(__name__)
        self.repository = repository
        self._state = WorkspaceState()
        self._load_state()

    def _load_state(self) -> None:
        try:
            self._state = self.repository.load()
        except FileNotFoundError:
            self._state = WorkspaceState()
        except ValueError as exc:
            self.logger.error("%s; starting with default workspace state", exc)
            self._state = WorkspaceState()
        except OSError as exc:
            self.logger.error("Error reading workspace state: %s", exc)
            self._state = WorkspaceState()

    def _save_state(self) -> None:
        try:
            self.repository.save(self._state)
        except OSError as exc:
            self.logger.error("Error saving workspace state: %s", exc)
            raise

    @property
    def state(self) -> WorkspaceState:
        return deepcopy(self._state)

    def update_state(self, state: WorkspaceState) -> None:
        self._state = deepcopy(state)
        self._save_state()

    def reload(self) -> None:
        self._load_state()
