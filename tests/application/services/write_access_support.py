"""Explicit collaborators for the application mutation boundary (no UI imports)."""

from contextlib import contextmanager
from ost_visualizer.application.dtos.collaboration_dtos import (
    DatabaseMutationResult,
    MutationOutcomeStatus,
)

OPERATION_ID = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
SESSION_ID = "11111111-2222-3333-4444-555555555555"


class _EventBus:
    def __init__(self):
        self.published = []

    def publish(self, event_type, **payload):
        event_type(**payload)
        self.published.append((event_type, payload))


class _CapabilityService:
    def __init__(self, editable: bool, denied_resource=None):
        self.editable = editable
        self.denied_resource = denied_resource
        self.requests = []

    def is_editable(self, database_id, resource=None):
        self.requests.append((database_id, resource))
        return self.editable and (resource is None or resource != self.denied_resource)


class _Recorder:
    def __init__(self):
        self.changes = []

    def record(self, resource, operation, *, changed_fields=(), payload=""):
        self.changes.append((resource, operation, changed_fields, payload))


class _MutationExecutor:
    def __init__(self, *, status=MutationOutcomeStatus.COMMITTED, conflict=None):
        self.calls = 0
        self.requests = []
        self.status = status
        self.conflict = conflict
        self.resulting_versions = {}
        self.recorder = _Recorder()

    def execute(self, request, operation):
        self.calls += 1
        self.requests.append(request)
        value = (
            operation(self.recorder)
            if self.status == MutationOutcomeStatus.COMMITTED
            else None
        )
        return DatabaseMutationResult(
            operation_id=request.operation_id,
            outcome_status=self.status,
            value=value,
            conflict=self.conflict,
            resulting_versions=self.resulting_versions,
        )


class _SessionRegistry:
    def __init__(self):
        self.tokens = ()
        self.requests = []

    def get(self, database_id):
        self.requests.append(("session", database_id))
        return SESSION_ID

    def lock_tokens(self, database_id, resources):
        self.requests.append(("locks", database_id, resources))
        return self.tokens


class _ConcurrencyTokens:
    def __init__(self):
        self.load_calls = 0
        self.loaded = []
        self.expected = ()
        self.applied = []
        self.scope = []

    def ensure_resources_loaded(self, database_id, resources):
        self.load_calls += 1
        self.loaded.append((database_id, resources))

    @contextmanager
    def mutation_scope(self, database_id):
        self.scope.append(("enter", database_id))
        try:
            yield
        finally:
            self.scope.append(("exit", database_id))

    def expected_versions(self, _database_id, _resources):
        return self.expected

    def apply_result(self, database_id, versions):
        self.applied.append((database_id, versions))
