import unittest
from dataclasses import replace
from ost_visualizer.application.dtos.collaboration_dtos import (
    CollaborationMutationType,
    PendingMutationState,
    QueuedMutationRequest,
    ResourceRef,
)
from ost_visualizer.application.services.pending_mutation_registry import (
    PendingMutationRegistry,
)


def _request(
    *,
    operation_id: str = "00000000-0000-0000-0000-000000000001",
    resource_id: str = "10",
) -> QueuedMutationRequest:
    return QueuedMutationRequest(
        database_id="database",
        operation_id=operation_id,
        mutation_type=CollaborationMutationType.PLAN_GEOMETRY,
        owning_surface="main-plan",
        resources=(ResourceRef("takeoff", resource_id, 1),),
        dependency_resources=(ResourceRef("page", "20", 1),),
        bid_uid=1,
        page_uid="20",
        payload={"positions": [(resource_id, [1.0, 2.0])]},
    )


class PendingMutationRegistryTests(unittest.TestCase):
    def test_registry_preserves_submission_order_for_overlapping_resources(self):
        registry = PendingMutationRegistry()
        request = _request()
        queued = registry.begin(request, runtime_generation=4)
        overlapping = _request(operation_id="00000000-0000-0000-0000-000000000002")
        other = registry.begin(overlapping)
        snapshot = registry.for_database("database")
        self.assertEqual(snapshot, (queued, other))
        executing = registry.transition(
            request.operation_id,
            PendingMutationState.EXECUTING,
        )
        self.assertEqual(
            executing, replace(queued, state=PendingMutationState.EXECUTING)
        )
        self.assertIs(registry.get(request.operation_id), executing)
        projecting = registry.transition(
            request.operation_id,
            PendingMutationState.PROJECTING,
        )
        self.assertEqual(
            projecting, replace(queued, state=PendingMutationState.PROJECTING)
        )
        self.assertEqual(registry.for_database("database"), (projecting, other))
        self.assertEqual(snapshot, (queued, other))
        self.assertEqual(queued.state, PendingMutationState.QUEUED)
        self.assertIs(registry.finish(request.operation_id), projecting)
        self.assertIsNone(registry.get(request.operation_id))
        self.assertEqual(registry.for_database("database"), (other,))
        self.assertIs(registry.finish(overlapping.operation_id), other)
        self.assertEqual(registry.for_database("database"), ())

    def test_registry_rejects_invalid_transition_and_clears_one_database(self):
        registry = PendingMutationRegistry()
        first = _request()
        second = QueuedMutationRequest(
            database_id="other",
            operation_id="00000000-0000-0000-0000-000000000002",
            mutation_type=CollaborationMutationType.ANNOTATION_UPDATE,
            owning_surface="detached-annotation",
            resources=(ResourceRef("annotation", "text/4", 2),),
        )
        first_pending = registry.begin(first)
        second_pending = registry.begin(second)
        with self.assertRaisesRegex(ValueError, "Invalid pending mutation transition"):
            registry.transition(first.operation_id, PendingMutationState.PROJECTING)
        self.assertIs(registry.get(first.operation_id), first_pending)
        cleared = registry.clear_database("database")
        self.assertEqual(
            tuple(item.request.operation_id for item in cleared), (first.operation_id,)
        )
        self.assertIs(registry.get(second.operation_id), second_pending)
        self.assertEqual(registry.for_database("database"), ())
        self.assertEqual(registry.clear_database("database"), ())
        self.assertEqual(registry.for_database("other"), (second_pending,))

    def test_transition_matrix_preserves_metadata_and_rejects_invalid_edges(self):
        state = PendingMutationState
        paths = {
            state.QUEUED: (),
            state.EXECUTING: (state.EXECUTING,),
            state.PROJECTING: (state.EXECUTING, state.PROJECTING),
            state.RECOVERING: (state.RECOVERING,),
            state.UNCERTAIN: (state.EXECUTING, state.UNCERTAIN),
        }
        allowed = {
            state.QUEUED: {state.QUEUED, state.EXECUTING, state.RECOVERING},
            state.EXECUTING: {
                state.EXECUTING,
                state.PROJECTING,
                state.RECOVERING,
                state.UNCERTAIN,
            },
            state.PROJECTING: {state.PROJECTING, state.RECOVERING, state.UNCERTAIN},
            state.RECOVERING: {state.RECOVERING, state.PROJECTING, state.UNCERTAIN},
            state.UNCERTAIN: {state.UNCERTAIN, state.RECOVERING, state.PROJECTING},
        }
        for source in state:
            for target in state:
                with self.subTest(source=source, target=target):
                    registry = PendingMutationRegistry()
                    request = _request()
                    before = registry.begin(request, runtime_generation=4)
                    for step in paths[source]:
                        before = registry.transition(
                            request.operation_id, step, message="retained"
                        )
                    if target not in allowed[source]:
                        with self.assertRaisesRegex(
                            ValueError, "Invalid pending mutation transition"
                        ):
                            registry.transition(request.operation_id, target)
                        self.assertIs(registry.get(request.operation_id), before)
                        continue
                    changed = registry.transition(request.operation_id, target)
                    self.assertEqual(changed, replace(before, state=target))
                    self.assertIs(registry.get(request.operation_id), changed)
                    reset = registry.transition(
                        request.operation_id, target, runtime_generation=0, message=""
                    )
                    self.assertEqual(
                        reset, replace(changed, runtime_generation=0, message="")
                    )

    def test_duplicate_operation_id_rejection_preserves_original_owner(self):
        registry = PendingMutationRegistry()
        request = _request()
        original = registry.begin(request, runtime_generation=7)
        for candidate in (request, replace(request, database_id="other")):
            with self.subTest(database=candidate.database_id):
                with self.assertRaisesRegex(
                    ValueError, "already uses this operation ID"
                ):
                    registry.begin(candidate)
                self.assertIs(registry.get(request.operation_id), original)
                self.assertEqual(registry.for_database("other"), ())

    def test_missing_and_finished_mutations_cannot_transition(self):
        registry = PendingMutationRegistry()
        request = _request()
        self.assertIsNone(registry.get(request.operation_id))
        self.assertIsNone(registry.finish(request.operation_id))
        with self.assertRaisesRegex(ValueError, "no longer registered"):
            registry.transition(request.operation_id, PendingMutationState.EXECUTING)
        original = registry.begin(request)
        self.assertIs(registry.finish(request.operation_id), original)
        self.assertIsNone(registry.finish(request.operation_id))
        with self.assertRaisesRegex(ValueError, "no longer registered"):
            registry.transition(request.operation_id, PendingMutationState.RECOVERING)
