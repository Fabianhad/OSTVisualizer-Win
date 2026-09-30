from ost_visualizer.application.dtos.collaboration_dtos import (
    CollaborationMutationType,
    PendingMutationState,
    QueuedMutationRequest,
    ResourceRef,
    canonical_mutation_request_hash,
)
import uuid
import unittest
from ost_visualizer.application.dtos.collaboration_dtos import (
    AuthoritativeMutationResult,
    ChangeOperation,
    CollaborationMutationType,
    CollaborationPollingPolicy,
    CollaborationShutdownState,
    CollaborationStatus,
    ConcurrencyToken,
    DatabaseChange,
    DatabaseChangeBatch,
    DatabaseChangePollResult,
    DatabaseMutationRequest,
    DatabaseMutationResult,
    DatabaseSession,
    DurableOperationResult,
    EditLeaseHandle,
    EditLeaseLoss,
    EditLeaseResult,
    HydratedDatabaseChangeBatch,
    MutationExecutionResult,
    MutationOutcomeStatus,
    PendingMutationState,
    PendingSqlOperationRecord,
    PresenceMode,
    QueuedMutationRequest,
    QueuedMutationResult,
    ReconciliationFailureKind,
    ReconciliationResult,
    ResourceLock,
    ResourceRef,
    SynchronizationConflict,
    SynchronizationConflictKind,
    SynchronizationState,
    queued_takeoff_preview_uid,
    session_identities_equal,
)
from ost_visualizer.application.events.app_events import AppEvents
import json
from dataclasses import replace
from ost_visualizer.application.dtos.collaboration_dtos import (
    CollaborationMutationType,
    DatabaseMutationRequest,
    DatabaseMutationResult,
    DurableOperationResult,
    MutationOutcomeStatus,
    PageSettingsPayload,
    PendingMutationState,
    PendingSqlOperationRecord,
    PlanPropertyPayload,
    ProjectImportPayload,
    ProjectWritePayload,
    QueuedMutationRequest,
    QueuedMutationResult,
    ResourceRef,
)
import sqlite3
from contextlib import contextmanager
from types import SimpleNamespace
from ost_visualizer.application.dtos.collaboration_dtos import (
    ConcurrencyToken,
    DatabaseMutationResult,
    ExpectedResourceVersion,
    MutationOutcomeStatus,
    ResourceRef,
)
from ost_visualizer.domain.entities.identity_refs import BidRef
from ost_visualizer.domain.entities.takeoff import Takeoff
from ost_visualizer.infrastructure.mdb.mdb_writer import MdbWriter
import tests.application.services.test_project_write_service as parity
from tests.helpers.mdb.operations import (
    _SqliteCursorWrapper,
    _SqliteDuplicateOps,
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


class CollaborationDtosCollaborationTests(unittest.TestCase):
    def test_edit_lease_result_rejects_incomplete_ownership_state(self):
        resource = ResourceRef("condition", "42", 8)
        handle = EditLeaseHandle(
            database_id="database",
            draft_id="draft",
            runtime_generation=1,
            operation_id="edit-condition",
            owning_surface="test",
            resources=(resource,),
        )
        with self.assertRaisesRegex(ValueError, "handle"):
            EditLeaseResult(True)
        with self.assertRaisesRegex(ValueError, "handle"):
            EditLeaseResult(False, handle=handle)

    def test_resource_reference_order_handles_optional_bid_context(self):
        context_free = ResourceRef("condition", "42")
        bid_scoped = ResourceRef("condition", "42", 8)
        self.assertEqual(
            sorted((bid_scoped, context_free)),
            [context_free, bid_scoped],
        )
        self.assertLess(context_free, bid_scoped)

    def test_session_identity_comparison_normalizes_uuid_text(self):
        self.assertTrue(
            session_identities_equal(
                "AAAAAAAA-BBBB-CCCC-DDDD-EEEEEEEEEEEE",
                "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
            )
        )
        self.assertFalse(session_identities_equal("session-a", "session-b"))
        self.assertFalse(session_identities_equal("session-a", "SESSION-A"))

    def test_queued_mutation_result_requires_current_keyword_shape(self):
        with self.assertRaises(TypeError):
            QueuedMutationResult("database", 1, "operation", True)

    def test_lease_loss_event_requires_the_typed_loss_payload(self):
        with self.assertRaises(TypeError):
            AppEvents.EDIT_LEASE_LOST()
        loss = EditLeaseLoss(
            database_id="database",
            draft_id="draft",
            runtime_generation=1,
            operation_id="edit-condition",
            owning_surface="test",
            resources=(ResourceRef("condition", "42", 8),),
            reason="trust-lost",
        )
        self.assertIs(AppEvents.EDIT_LEASE_LOST(loss).loss, loss)


class CollaborationPayloadContractTests(unittest.TestCase):
    def test_project_import_payload_is_typed_and_request_hash_is_stable(self):
        payload = ProjectImportPayload(
            source_path="C:/imports/project.ost",
            source_kind="ost",
            source_size=123,
            source_modified_ns=456,
            target_project_uid="9",
        )
        first = QueuedMutationRequest(
            database_id="database",
            operation_id=str(uuid.uuid4()),
            mutation_type=CollaborationMutationType.PROJECT_IMPORT,
            owning_surface="project-import",
            resources=(ResourceRef("project_bids", "9"),),
            payload=payload,
        )
        second = replace(first, operation_id=str(uuid.uuid4()))
        self.assertEqual(first.request_hash, second.request_hash)
        with self.assertRaisesRegex(ValueError, "OST or OSP"):
            replace(payload, source_kind="zip")

    def test_property_and_page_payloads_canonicalize_updates(self):
        first = PlanPropertyPayload.from_updates(
            "takeoff_text",
            [["10", {"FontSize": 12, "FontName": "Arial"}]],
        )
        second = PlanPropertyPayload.from_updates(
            "takeoff_text",
            [["10", {"FontName": "Arial", "FontSize": 12}]],
        )
        page = PageSettingsPayload.from_updates("scale", [["20", 1.0, 96.0]])
        self.assertEqual(first, second)
        self.assertEqual(first.decoded_updates()[0][0], "10")
        self.assertEqual(page.decoded_updates(), [["20", 1.0, 96.0]])

    def test_project_write_payload_is_typed_and_canonical(self):
        first = ProjectWritePayload.from_values(
            "rename_layer", {"name": "Coordination", "layer_uid": "10"}
        )
        second = ProjectWritePayload.from_values(
            "rename_layer", {"layer_uid": "10", "name": "Coordination"}
        )
        self.assertEqual(first, second)
        self.assertEqual(
            json.loads(first.values_json),
            {"layer_uid": "10", "name": "Coordination"},
        )
        with self.assertRaisesRegex(ValueError, "Unsupported queued project write"):
            ProjectWritePayload.from_values("unsupported_write", {})

    def test_sql_selected_page_is_not_a_collaboration_mutation_payload(self):
        with self.assertRaisesRegex(ValueError, "Unsupported page setting"):
            PageSettingsPayload.from_updates(
                "bid_selected_page",
                [["8", "22"]],
            )

    def test_database_request_requires_canonical_identity_and_hash(self):
        operation_id = str(uuid.uuid4())
        request = DatabaseMutationRequest(
            database_id="database",
            session_id="session",
            operation_id=operation_id,
            mutation_type=CollaborationMutationType.PROJECT_WRITE.value,
            request_hash="a" * 64,
            resources=(ResourceRef("takeoff", "10", 1),),
        )
        self.assertEqual(request.operation_id, operation_id)
        self.assertEqual(request.request_hash, "a" * 64)
        with self.assertRaises(TypeError):
            DatabaseMutationRequest(database_id="database", session_id="session")
        with self.assertRaisesRegex(ValueError, "result format version 1"):
            DatabaseMutationRequest(
                database_id="database",
                session_id="session",
                operation_id=str(uuid.uuid4()),
                mutation_type=CollaborationMutationType.PROJECT_WRITE.value,
                request_hash="a" * 64,
                result_format_version=2,
            )
        with self.assertRaisesRegex(ValueError, "types must be canonical"):
            DatabaseMutationRequest(
                database_id="database",
                session_id="session",
                operation_id=str(uuid.uuid4()),
                mutation_type="old_project_write",
                request_hash="a" * 64,
            )

    def test_queued_request_rejects_noncanonical_payload_format(self):
        with self.assertRaisesRegex(ValueError, "payload format version 1"):
            QueuedMutationRequest(
                database_id="database",
                operation_id=str(uuid.uuid4()),
                mutation_type=CollaborationMutationType.PLAN_GEOMETRY,
                owning_surface="main-plan",
                resources=(ResourceRef("takeoff", "10", 1),),
                payload_format_version=2,
            )


class PlanPropertyOwnershipTests(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.addCleanup(self.conn.close)
        self.conn.executescript(
            """
            CREATE TABLE Bids (UID INTEGER PRIMARY KEY);
            INSERT INTO Bids VALUES (7);
            CREATE TABLE BidAreas (UID INTEGER PRIMARY KEY, BidUID INTEGER);
            INSERT INTO BidAreas VALUES (1,7),(2,7),(3,7),(4,8);
            CREATE TABLE BidTakeoffs (UID INTEGER PRIMARY KEY, BidUID INTEGER,
                BidPageUID INTEGER, BidConditionUID INTEGER, BidAreaUID INTEGER,
                ParentUID INTEGER, Position BLOB);
            INSERT INTO BidTakeoffs VALUES
                (10,7,20,30,1,NULL,'0;0;10;0;10;10'),
                (11,7,20,30,2,NULL,'20;0;30;0;30;10'),
                (12,7,20,30,NULL,NULL,'40;0;50;0;50;10'),
                (13,7,20,30,1,10,'1;1;2;1;2;2');
        """
        )
        self.conn.commit()
        self.ops = _SqliteDuplicateOps(self.conn)
        manager = SimpleNamespace(
            connection=self.connection,
            use_committed_writer_for_reads=lambda _path: None,
        )
        self.transaction_writer = MdbWriter(conn_manager=manager)
        self.ops._connection = self.transaction_writer._connection
        self.service = parity.MdbSqlBehaviorParityTests._local_composite_service()
        self.service._project_data = SimpleNamespace(
            get_current_bid_ref=lambda: BidRef("database.mdb", "7"),
            get_all_takeoffs=self.takeoffs,
        )
        self.service._mutation_executor = SimpleNamespace(
            verify_plan_items_exist=lambda *args, **kwargs: MdbWriter.verify_plan_items_exist(
                self.ops, *args, **kwargs
            )
        )
        self.service._save_takeoffs_area = SimpleNamespace(
            execute=self.ops.save_takeoffs_area
        )
        self.service._execute_database_mutation = self.execute_mutation
        self.service._concurrency_tokens = SimpleNamespace(
            expected_versions=lambda _database, resources: tuple(
                ExpectedResourceVersion(resource, ConcurrencyToken(b"a" * 8))
                for resource in resources
            )
        )

    @contextmanager
    def connection(self, _path, *, autocommit):
        self.assertFalse(autocommit)
        yield SimpleNamespace(
            cursor=lambda: _SqliteCursorWrapper(self.conn),
            commit=self.conn.commit,
            rollback=self.conn.rollback,
        )

    def execute_mutation(self, database_id, _resources, operation, **_options):
        with self.transaction_writer._connection(database_id):
            value = operation(SimpleNamespace(record=lambda *_args, **_kwargs: None))
        return DatabaseMutationResult(
            operation_id="00000000-0000-0000-0000-000000000001",
            outcome_status=MutationOutcomeStatus.COMMITTED,
            value=value,
        )

    def test_external_parent_bindings_reject_incomplete_or_ambiguous_sources(self):
        from ost_visualizer.application.dtos.collaboration_dtos import (
            PlanItemsPastePayload,
        )
        from ost_visualizer.application.dtos.insert_takeoff_spec_dto import (
            InsertTakeoffSpec,
        )

        for sources, parent_uid in (
            (("missing",), "10"),
            (("10", "10"), "10"),
            (("10",), "0"),
        ):
            with self.subTest(sources=sources, parent_uid=parent_uid):
                with self.assertRaises(ValueError):
                    PlanItemsPastePayload(
                        source_bid_uid="7",
                        destination_bid_uid="7",
                        takeoff_source_uids=("10",),
                        takeoff_specs=(
                            InsertTakeoffSpec(
                                "30", "20", "1", [0, 0, 1, 1], parent_uid=parent_uid
                            ),
                        ),
                        takeoff_external_parent_sources=sources,
                    )

    def takeoffs(self):
        return [
            Takeoff(
                uid=str(uid),
                page_uid=str(page),
                condition_uid=str(condition),
                area_uid=str(area or "0"),
                parent_uid=str(parent or "0"),
            )
            for uid, page, condition, area, parent in self.conn.execute(
                "SELECT UID,BidPageUID,BidConditionUID,BidAreaUID,ParentUID FROM BidTakeoffs"
            )
        ]
