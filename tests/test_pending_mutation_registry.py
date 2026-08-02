import unittest
import uuid
from ost_visualizer.application.dtos.collaboration_dtos import (
    CollaborationMutationType,
    PendingMutationState,
    QueuedMutationRequest,
    ResourceRef,
    canonical_mutation_request_hash,
)
from ost_visualizer.application.services.pending_mutation_registry import (
    PendingMutationRegistry,
)


def _request(
    *,
    operation_id: str | None = None,
    resource_id: str = "10",
) -> QueuedMutationRequest:
    return QueuedMutationRequest(
        database_id="database",
        operation_id=operation_id or str(uuid.uuid4()),
        mutation_type=CollaborationMutationType.PLAN_GEOMETRY,
        owning_surface="main-plan",
        resources=(ResourceRef("takeoff", resource_id, 1),),
        dependency_resources=(ResourceRef("page", "20", 1),),
        bid_uid=1,
        page_uid="20",
        payload={"positions": [(resource_id, [1.0, 2.0])]},
    )


class QueuedMutationRequestTests(unittest.TestCase):
    def test_request_normalizes_identity_resources_and_hash(self):
        operation_id = str(uuid.uuid4()).upper()
        resource = ResourceRef("takeoff", "10", 1)
        request = QueuedMutationRequest(
            database_id="database",
            operation_id=operation_id,
            mutation_type=CollaborationMutationType.PLAN_GEOMETRY,
            owning_surface="main-plan",
            resources=(resource, resource),
            payload={"b": [2, 1], "a": True},
        )
        self.assertEqual(request.operation_id, str(uuid.UUID(operation_id)))
        self.assertEqual(request.resources, (resource,))
        self.assertEqual(len(request.request_hash), 64)
        self.assertEqual(
            request.request_hash,
            canonical_mutation_request_hash(
                {
                    "mutation_type": "plan_geometry",
                    "payload_format_version": 1,
                    "payload": {"a": True, "b": [2, 1]},
                }
            ),
        )

    def test_request_rejects_non_uuid(self):
        with self.assertRaises(ValueError):
            _request(operation_id="not-a-uuid")


class PendingMutationRegistryTests(unittest.TestCase):
    def test_registry_owns_transitions_and_allows_fifo_resource_overlap(self):
        registry = PendingMutationRegistry()
        request = _request()
        registry.begin(request, runtime_generation=4)
        overlapping = _request(resource_id="10")
        registry.begin(overlapping)
        executing = registry.transition(
            request.operation_id,
            PendingMutationState.EXECUTING,
        )
        self.assertEqual(executing.state, PendingMutationState.EXECUTING)
        projecting = registry.transition(
            request.operation_id,
            PendingMutationState.PROJECTING,
        )
        self.assertEqual(projecting.runtime_generation, 4)
        self.assertIsNotNone(registry.finish(request.operation_id))
        self.assertIsNotNone(registry.finish(overlapping.operation_id))

    def test_registry_rejects_invalid_transition_and_clears_one_database(self):
        registry = PendingMutationRegistry()
        first = _request()
        second = QueuedMutationRequest(
            database_id="other",
            operation_id=str(uuid.uuid4()),
            mutation_type=CollaborationMutationType.ANNOTATION_UPDATE,
            owning_surface="detached-annotation",
            resources=(ResourceRef("annotation", "text/4", 2),),
        )
        registry.begin(first)
        registry.begin(second)
        with self.assertRaises(ValueError):
            registry.transition(first.operation_id, PendingMutationState.PROJECTING)
        cleared = registry.clear_database("database")
        self.assertEqual(
            tuple(item.request.operation_id for item in cleared), (first.operation_id,)
        )
        self.assertIsNotNone(registry.get(second.operation_id))


if __name__ == "__main__":
    unittest.main()
