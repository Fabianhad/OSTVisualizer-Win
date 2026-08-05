from copy import deepcopy
from ost_visualizer.domain.aggregates.workspace_state_aggregate import (
    WorkspaceStateAggregate,
)
from ost_visualizer.domain.entities.workspace_state import WorkspaceState


class InMemoryWorkspaceStateRepository:
    """Complete in-memory repository for presentation workflow tests."""

    def __init__(self, initial_state: WorkspaceState | None = None) -> None:
        self._state = deepcopy(initial_state or WorkspaceState())

    def load(self) -> WorkspaceState:
        return deepcopy(self._state)

    def save(self, state: WorkspaceState) -> None:
        self._state = deepcopy(state)


def make_workspace_state_model() -> WorkspaceStateAggregate:
    return WorkspaceStateAggregate(InMemoryWorkspaceStateRepository())


def with_workspace_state(constructor):
    """Supply the real aggregate contract to otherwise unrelated UI tests."""

    class WorkspaceStateFixture(constructor):
        def __init__(self, *args, **kwargs):
            if "workspace_state_model" not in kwargs:
                kwargs["workspace_state_model"] = make_workspace_state_model()
            super().__init__(*args, **kwargs)

    WorkspaceStateFixture.__name__ = constructor.__name__
    WorkspaceStateFixture.__qualname__ = constructor.__qualname__
    return WorkspaceStateFixture
