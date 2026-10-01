import logging
import unittest
from ost_visualizer.application.services.base_write_service import (
    BaseWriteService,
    DatabaseMutationWriteService,
)
from ost_visualizer.application.interfaces.i_mdb_connection_manager import (
    DatabaseConnectionUnavailableError,
)
from ost_visualizer.application.dtos.collaboration_dtos import (
    ChangeOperation,
    ConcurrencyToken,
    ExpectedResourceVersion,
    MutationOutcomeStatus,
    ResourceRef,
    SynchronizationConflict,
    SynchronizationConflictKind,
)
from ost_visualizer.application.events.app_events import AppEvents
from tests.application.services.write_access_support import (
    OPERATION_ID,
    SESSION_ID,
    _CapabilityService,
    _ConcurrencyTokens,
    _EventBus,
    _MutationExecutor,
    _SessionRegistry,
)


class _BoundaryFixture(unittest.TestCase):
    def setUp(self):
        self.capability = _CapabilityService(editable=True)
        self.executor = _MutationExecutor()
        self.tokens = _ConcurrencyTokens()
        self.sessions = _SessionRegistry()
        self.events = _EventBus()
        self.reloads = []

    def service(self):
        return DatabaseMutationWriteService(
            reload_database=lambda db: self.reloads.append(db) or True,
            event_bus=self.events,
            mutation_executor=self.executor,
            session_registry=self.sessions,
            concurrency_tokens=self.tokens,
            database_capability_service=self.capability,
            logger=logging.getLogger("test.mutation_boundary"),
        )

    def forbidden_operation(self, _recorder):
        self.fail("rejected mutation must not invoke the write")


class DatabaseMutationConnectionFailureTests(_BoundaryFixture):
    def test_mutation_service_returns_failed_result_for_connection_exhaustion(self):
        message = "Restart OST Visualizer and try again."

        class UnavailableExecutor(_MutationExecutor):
            def execute(self, request, operation):
                self.calls += 1
                raise DatabaseConnectionUnavailableError(message)

        self.executor = UnavailableExecutor()
        with self.assertLogs("test.mutation_boundary", level="WARNING"):
            result = self.service()._execute_database_mutation(
                "exhausted.mdb",
                (ResourceRef("takeoffs_collection", "7", 7),),
                self.forbidden_operation,
                operation_id=OPERATION_ID,
            )
        self.assertEqual(
            result.outcome_status, MutationOutcomeStatus.FAILED_BEFORE_COMMIT
        )
        self.assertEqual(result.operation_id, OPERATION_ID)
        self.assertEqual(result.failure_reason, message)
        self.assertFalse(result.commit_attempted)
        self.assertEqual(self.executor.calls, 1)
        self.assertEqual(self.tokens.applied, [])
        self.assertEqual(
            self.tokens.scope, [("enter", "exhausted.mdb"), ("exit", "exhausted.mdb")]
        )
        self.assertEqual(self.events.published, [])
        self.assertEqual(self.reloads, [])


class BaseWriteServiceCollaborationTests(_BoundaryFixture):
    def _conflict(self, resource, reason, kind, *, publish=True):
        fixture = self

        class UnlockedEventBus(_EventBus):
            def publish(self, event_type, **payload):
                fixture.assertEqual(
                    fixture.tokens.scope,
                    [("enter", "database"), ("exit", "database")],
                )
                super().publish(event_type, **payload)

        self.events = UnlockedEventBus()
        self.executor = _MutationExecutor(
            status=MutationOutcomeStatus.CONFLICT,
            conflict=SynchronizationConflict("database", resource, reason, kind=kind),
        )
        result = self.service()._execute_database_mutation(
            "database",
            (resource,),
            self.forbidden_operation,
            operation_id=OPERATION_ID,
            publish_conflict_event=publish,
        )
        self.assertEqual(result.outcome_status, MutationOutcomeStatus.CONFLICT)
        self.assertIs(result.conflict, self.executor.conflict)
        self.assertEqual(self.tokens.applied, [])
        self.assertEqual(self.reloads, [])

    def test_project_write_conflict_publishes_typed_event(self):
        self._conflict(
            ResourceRef("condition", "42", 8),
            "stale update",
            SynchronizationConflictKind.OPTIMISTIC_CONCURRENCY,
        )
        self.assertEqual(
            self.events.published,
            [
                (
                    AppEvents.SYNCHRONIZATION_CONFLICT,
                    {
                        "database_id": "database",
                        "resource_type": "condition",
                        "resource_id": "42",
                        "bid_uid": "8",
                        "message": "stale update",
                        "blocks_database": False,
                    },
                )
            ],
        )

    def test_project_write_session_conflict_blocks_the_database(self):
        self._conflict(
            ResourceRef("database", "database"),
            "session expired",
            SynchronizationConflictKind.SESSION,
        )
        self.assertEqual(
            self.events.published,
            [
                (
                    AppEvents.SYNCHRONIZATION_CONFLICT,
                    {
                        "database_id": "database",
                        "resource_type": "database",
                        "resource_id": "database",
                        "bid_uid": "",
                        "message": "session expired",
                        "blocks_database": True,
                    },
                )
            ],
        )

    def test_conflict_publication_can_be_owned_by_the_caller(self):
        self._conflict(
            ResourceRef("condition", "42", 8),
            "stale",
            SynchronizationConflictKind.OPTIMISTIC_CONCURRENCY,
            publish=False,
        )
        self.assertEqual(self.events.published, [])


class UIAccessPlanEditingTests(_BoundaryFixture):
    def test_application_mutation_boundary_rejects_revoked_database_access(self):
        self.capability.editable = False
        with self.assertLogs("test.mutation_boundary", level="WARNING"):
            result = self.service()._execute_database_mutation(
                "sql-db",
                (ResourceRef("takeoff", "41", 7),),
                self.forbidden_operation,
            )
        self.assertEqual(result.outcome_status, MutationOutcomeStatus.REJECTED)
        self.assertEqual(self.executor.calls, 0)
        self.assertEqual(self.tokens.load_calls, 0)
        self.assertEqual(self.capability.requests, [("sql-db", None)])
        self.assertEqual(self.sessions.requests, [])
        self.assertEqual(self.events.published, [])
        self.assertEqual(self.tokens.scope, [("enter", "sql-db"), ("exit", "sql-db")])

    def test_application_mutation_boundary_preserves_editable_access_path(self):
        resource = ResourceRef("takeoff", "41", 7)
        writes = []

        def write(recorder):
            writes.append("written")
            recorder.record(resource, ChangeOperation.UPDATE, changed_fields=("name",))
            return ["41"]

        self.executor.resulting_versions = {resource: ConcurrencyToken(b"\x02" * 8)}
        result = self.service()._execute_database_mutation(
            "access-db",
            (resource,),
            write,
            operation_id=OPERATION_ID,
        )
        self.assertEqual(result.outcome_status, MutationOutcomeStatus.COMMITTED)
        self.assertEqual(result.value, ["41"])
        self.assertEqual(writes, ["written"])
        self.assertEqual(self.executor.calls, 1)
        self.assertEqual(
            self.executor.recorder.changes,
            [(resource, ChangeOperation.UPDATE, ("name",), "")],
        )
        self.assertEqual(self.tokens.loaded, [("access-db", (resource,))])
        self.assertEqual(
            self.tokens.applied,
            [("access-db", {resource: ConcurrencyToken(b"\x02" * 8)})],
        )
        self.assertEqual(
            self.capability.requests, [("access-db", None), ("access-db", resource)]
        )
        self.assertEqual(self.events.published, [])
        self.assertEqual(self.reloads, [])

    def test_application_mutation_boundary_rejects_locked_resource(self):
        first = ResourceRef("takeoff", "40", 7)
        locked = ResourceRef("takeoff", "41", 7)
        self.capability.denied_resource = locked
        with self.assertLogs("test.mutation_boundary", level="WARNING"):
            result = self.service()._execute_database_mutation(
                "sql-db",
                (first, locked),
                self.forbidden_operation,
            )
        self.assertEqual(result.outcome_status, MutationOutcomeStatus.REJECTED)
        self.assertEqual(self.executor.calls, 0)
        self.assertEqual(self.tokens.load_calls, 0)
        self.assertEqual(
            self.capability.requests,
            [("sql-db", None), ("sql-db", first), ("sql-db", locked)],
        )
        self.assertEqual(self.sessions.requests, [])
        self.assertEqual(self.events.published, [])

    def test_request_preserves_captured_versions_and_lock_ownership(self):
        first = ResourceRef("condition", "41", 7)
        second = ResourceRef("condition", "42", 7)
        original = ExpectedResourceVersion(first, ConcurrencyToken(b"\x01" * 8))
        latest = ExpectedResourceVersion(first, ConcurrencyToken(b"\x02" * 8))
        other = ExpectedResourceVersion(second, ConcurrencyToken(b"\x03" * 8))
        self.tokens.expected = (latest, other)
        self.sessions.tokens = ("lease-token",)
        self.service()._execute_database_mutation(
            "sql-db",
            (first, second),
            lambda _recorder: True,
            operation_id=OPERATION_ID,
            request_hash="a" * 64,
            block_bid_child_locks=True,
            block_bid_active_editors=True,
            captured_versions=(original,),
        )
        self.assertEqual(len(self.executor.requests), 1)
        request = self.executor.requests[0]
        self.assertEqual(request.database_id, "sql-db")
        self.assertEqual(request.session_id, SESSION_ID)
        self.assertEqual(request.operation_id, OPERATION_ID)
        self.assertEqual(request.resources, (first, second))
        self.assertEqual(request.expected_versions, (original, other))
        self.assertEqual(request.required_lock_tokens, ("lease-token",))
        self.assertEqual(request.request_hash, "a" * 64)
        self.assertTrue(request.block_bid_child_locks)
        self.assertTrue(request.block_bid_active_editors)
        self.assertEqual(self.tokens.expected, (latest, other))

    def test_noncommitted_outcomes_never_advance_tokens_or_trigger_reload(self):
        for status in (
            MutationOutcomeStatus.REJECTED,
            MutationOutcomeStatus.FAILED_BEFORE_COMMIT,
            MutationOutcomeStatus.COMMIT_STATUS_UNKNOWN,
        ):
            with self.subTest(status=status):
                self.executor.status = status
                result = self.service()._execute_database_mutation(
                    "sql-db",
                    (ResourceRef("takeoff", "41", 7),),
                    self.forbidden_operation,
                )
                self.assertEqual(result.outcome_status, status)
                self.assertEqual(self.tokens.applied, [])
                self.assertEqual(self.events.published, [])
                self.assertEqual(self.reloads, [])

    def test_unexpected_write_exception_releases_scope_without_success_publication(
        self,
    ):
        resource = ResourceRef("condition", "41", 7)

        def fail(_recorder):
            raise RuntimeError("write failed")

        service = self.service()
        with self.assertRaisesRegex(RuntimeError, "write failed"):
            service._execute_database_mutation("sql-db", (resource,), fail)
        self.assertEqual(self.executor.calls, 1)
        self.assertEqual(self.tokens.scope, [("enter", "sql-db"), ("exit", "sql-db")])
        self.assertEqual(self.tokens.applied, [])
        self.assertEqual(self.events.published, [])
        self.assertEqual(self.reloads, [])
        result = service._execute_database_mutation(
            "sql-db", (resource,), lambda _recorder: "retry accepted"
        )
        self.assertEqual(result.value, "retry accepted")
        self.assertEqual(result.outcome_status, MutationOutcomeStatus.COMMITTED)
        self.assertEqual(self.executor.calls, 2)
        self.assertEqual(
            self.tokens.scope, [("enter", "sql-db"), ("exit", "sql-db")] * 2
        )


class BaseWriteRefreshTests(unittest.TestCase):
    def test_reload_then_notify_preserves_targeted_projection_flags(self):
        events = _EventBus()
        calls = []

        def reload(path):
            self.assertEqual(events.published, [])
            calls.append(path)
            return True

        service = BaseWriteService(reload, events)
        self.assertTrue(
            service.reload_and_notify(
                "db.mdb",
                image_sources_unchanged=True,
                mesh_scene_unchanged=True,
                page_scale_uids=("7", "9"),
            )
        )
        self.assertEqual(calls, ["db.mdb"])
        self.assertEqual(
            events.published,
            [
                (
                    AppEvents.DATABASE_REFRESHED,
                    {
                        "file_path": "db.mdb",
                        "image_sources_unchanged": True,
                        "mesh_scene_unchanged": True,
                        "page_scale_uids": ("7", "9"),
                    },
                )
            ],
        )

    def test_failed_or_raising_reload_does_not_publish_success(self):
        for raises in (False, True):
            with self.subTest(raises=raises):
                events = _EventBus()
                calls = []

                def reload(path):
                    calls.append(path)
                    if raises:
                        raise OSError("read failed")
                    return False

                service = BaseWriteService(
                    reload, events, logging.getLogger("test.reload")
                )
                if raises:
                    with self.assertLogs("test.reload", level="WARNING"):
                        self.assertFalse(service.reload_and_notify("db.mdb"))
                else:
                    self.assertFalse(service.reload_and_notify("db.mdb"))
                self.assertEqual(calls, ["db.mdb"])
                self.assertEqual(events.published, [])
