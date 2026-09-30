import unittest
from contextlib import nullcontext
from types import SimpleNamespace
from ost_visualizer.application.dtos.collaboration_dtos import (
    DatabaseMutationResult,
    MutationOutcomeStatus,
    ResourceRef,
)
from ost_visualizer.application.services.annotation_write_service import (
    AnnotationWriteService,
)
from ost_visualizer.application.services.base_write_service import (
    DatabaseMutationWriteService,
)
from ost_visualizer.domain.entities.identity_refs import BidRef
from ost_visualizer.presentation.components.plan_view.components.input_handler import (
    InputHandlerMixin,
)
from ost_visualizer.presentation.components.plan_view.view import TakeoffPlanView
from ost_visualizer.presentation.modes.cursor import CURSOR_MODE_PLACE


class _EventBus:
    def publish(self, *_args, **_kwargs):
        pass


class _CapabilityService:
    def __init__(self, editable: bool, denied_resource=None) -> None:
        self.editable = editable
        self.denied_resource = denied_resource
        self.requests = []

    def is_editable(self, database_id, resource=None) -> bool:
        self.requests.append((database_id, resource))
        return self.editable and (resource is None or resource != self.denied_resource)


class _MutationExecutor:
    def __init__(self) -> None:
        self.calls = 0

    def execute(self, request, operation):
        self.calls += 1
        return DatabaseMutationResult(
            operation_id=request.operation_id,
            outcome_status=MutationOutcomeStatus.COMMITTED,
            value=operation(SimpleNamespace()),
        )


class _SessionRegistry:
    def get(self, _database_id):
        return "session"

    def lock_tokens(self, _database_id, _resources):
        return ()


class _ConcurrencyTokens:
    def __init__(self) -> None:
        self.load_calls = 0

    def ensure_resources_loaded(self, _database_id, _resources):
        self.load_calls += 1

    def mutation_scope(self, _database_id):
        return nullcontext()

    def expected_versions(self, _database_id, _resources):
        return ()

    def apply_result(self, _database_id, _versions):
        pass
