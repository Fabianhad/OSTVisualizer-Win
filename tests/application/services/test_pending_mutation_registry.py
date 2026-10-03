import threading
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
from tests.helpers.lock_guard import guard_mapping


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

    def test_registry_rejects_invalid_transition_and_isolates_databases(self):
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
        # Metadata is only ever released operation by operation; finishing one
        # database's operation leaves every other database's metadata intact.
        self.assertEqual(registry.for_database("database"), (first_pending,))
        self.assertEqual(registry.for_database("other"), (second_pending,))
        self.assertIs(registry.finish(first.operation_id), first_pending)
        self.assertIs(registry.get(second.operation_id), second_pending)
        self.assertEqual(registry.for_database("database"), ())
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


class PendingMutationRegistryConcurrencyTests(unittest.TestCase):
    def _guarded(self):
        registry = PendingMutationRegistry()
        registry._mutations = guard_mapping(registry._lock, registry._mutations)
        return registry

    def test_every_public_operation_touches_the_table_only_while_locked(self):
        registry = self._guarded()
        request = _request()
        other = _request(operation_id="00000000-0000-0000-0000-000000000002")
        registry.begin(request)
        registry.begin(other)
        registry.get(request.operation_id)
        registry.for_database("database")
        registry.transition(request.operation_id, PendingMutationState.EXECUTING)
        with self.assertRaises(ValueError):
            registry.transition(request.operation_id, PendingMutationState.QUEUED)
        with self.assertRaises(ValueError):
            registry.transition("missing", PendingMutationState.EXECUTING)
        with self.assertRaises(ValueError):
            registry.begin(request)
        registry.finish(request.operation_id)
        registry.finish(request.operation_id)
        self.assertEqual(
            [p.request for p in registry.for_database("database")], [other]
        )
        with self.assertRaisesRegex(AssertionError, "without the lock"):
            registry._mutations.get(other.operation_id)

    def test_racing_begins_for_one_operation_id_admit_exactly_one_owner(self):
        registry = PendingMutationRegistry()
        racers = 8
        start = threading.Barrier(racers)
        outcomes = []

        def race(database):
            request = replace(_request(), database_id=database)
            start.wait(10.0)
            try:
                outcomes.append(("owner", registry.begin(request)))
            except ValueError as error:
                outcomes.append(("refused", str(error)))

        threads = [
            threading.Thread(target=race, args=(f"database-{index}",))
            for index in range(racers)
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(10.0)
            self.assertFalse(thread.is_alive())
        owners = [value for kind, value in outcomes if kind == "owner"]
        self.assertEqual(len(owners), 1)
        self.assertEqual(
            [value for kind, value in outcomes if kind == "refused"],
            ["A pending mutation already uses this operation ID"] * (racers - 1),
        )
        owner = owners[0]
        self.assertIs(registry.get(owner.request.operation_id), owner)
        self.assertEqual(registry.for_database(owner.request.database_id), (owner,))
        for index in range(racers):
            if f"database-{index}" != owner.request.database_id:
                self.assertEqual(registry.for_database(f"database-{index}"), ())

    def test_concurrent_lifecycles_of_distinct_operations_do_not_interfere(self):
        registry = PendingMutationRegistry()
        workers = 6
        start = threading.Barrier(workers)
        finished = {}

        def lifecycle(index):
            request = replace(
                _request(operation_id=f"00000000-0000-0000-0000-{index:012d}"),
                database_id=f"database-{index % 2}",
            )
            start.wait(10.0)
            registry.begin(request, runtime_generation=index)
            registry.transition(request.operation_id, PendingMutationState.EXECUTING)
            registry.transition(
                request.operation_id,
                PendingMutationState.PROJECTING,
                message=f"message-{index}",
            )
            finished[index] = registry.finish(request.operation_id)

        threads = [
            threading.Thread(target=lifecycle, args=(index,))
            for index in range(workers)
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(10.0)
            self.assertFalse(thread.is_alive())
        self.assertEqual(sorted(finished), list(range(workers)))
        for index, pending in finished.items():
            self.assertEqual(pending.state, PendingMutationState.PROJECTING)
            self.assertEqual(pending.runtime_generation, index)
            self.assertEqual(pending.message, f"message-{index}")
        self.assertEqual(registry.for_database("database-0"), ())
        self.assertEqual(registry.for_database("database-1"), ())


class PendingMutationRegistryBeginTests(unittest.TestCase):
    def test_begin_records_queued_state_message_and_runtime_generation(self):
        registry = PendingMutationRegistry()
        default = registry.begin(_request())
        explicit = registry.begin(
            _request(operation_id="00000000-0000-0000-0000-000000000002"),
            runtime_generation=9,
        )
        self.assertEqual(
            (default.state, default.runtime_generation, default.message),
            (PendingMutationState.QUEUED, 0, ""),
        )
        self.assertEqual(
            (explicit.state, explicit.runtime_generation, explicit.message),
            (PendingMutationState.QUEUED, 9, ""),
        )
        self.assertIs(registry.get(default.request.operation_id), default)
        self.assertIs(registry.get(explicit.request.operation_id), explicit)
