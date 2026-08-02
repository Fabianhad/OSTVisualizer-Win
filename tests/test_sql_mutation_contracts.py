import json
import tempfile
import unittest
import uuid
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
from ost_visualizer.application.dtos.collaboration_dtos import (
    CollaborationMutationType,
    DatabaseMutationResult,
    DatabaseMutationRequest,
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
from ost_visualizer.application.services.sql_collaboration_coordinator import (
    SqlCollaborationCoordinator,
)
from ost_visualizer.application.services.project_write_service import (
    ProjectWriteService,
)
from ost_visualizer.infrastructure.persistence.repositories.json_pending_sql_operation_repository import (
    JsonPendingSqlOperationRepository,
)
from ost_visualizer.infrastructure.sql.writer import SqlProjectWriter, _SqlMutationState


class SqlMutationContractTests(unittest.TestCase):
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

    def test_project_import_enters_canonical_queue_with_authoritative_result(self):
        payload = ProjectImportPayload(
            source_path="C:/imports/project.ost",
            source_kind="ost",
            source_size=123,
            source_modified_ns=456,
            target_project_uid="9",
        )
        value = {
            "project_uids": {"target": "9"},
            "bid_uids": {"b": "10"},
            "page_uids": {"p": "20"},
            "condition_uids": {"c": "30"},
            "layer_uids": {"l": "40"},
            "area_uids": {"r": "50"},
            "takeoff_uids": {"t": "60"},
            "annotation_uids": {"a": "70"},
        }
        captured = {}
        provider = SimpleNamespace(
            queue_request=lambda request, execute, callback: (
                captured.update(
                    request=request,
                    execute=execute,
                    callback=callback,
                )
                or 17
            )
        )
        service = ProjectWriteService.__new__(ProjectWriteService)
        service._sql_collaboration_provider = lambda: provider
        service._execute_database_mutation = lambda *_args, **_kwargs: (
            DatabaseMutationResult(
                operation_id=captured["request"].operation_id,
                outcome_status=MutationOutcomeStatus.COMMITTED,
                value=value,
                commit_attempted=True,
            )
        )
        sequence = service.queue_project_import(
            "database", "9", payload, lambda _recorder: value, lambda _result: None
        )
        execution = captured["execute"]()
        self.assertEqual(sequence, 17)
        self.assertEqual(
            captured["request"].mutation_type,
            CollaborationMutationType.PROJECT_IMPORT,
        )
        self.assertEqual(execution.outcome_status, MutationOutcomeStatus.COMMITTED)
        self.assertEqual(execution.authoritative_result.affected_page_uids, ("20",))
        self.assertEqual(
            execution.authoritative_result.affected_condition_uids, ("30",)
        )

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
            ProjectWritePayload.from_values("legacy_write", {})

    def test_sql_selected_page_is_presence_state_not_a_durable_mutation(self):
        service = SimpleNamespace(
            uses_sql_collaboration_mutations=lambda _database_id: True,
            queue_page_settings=lambda *_args, **_kwargs: self.fail(
                "Selected-page navigation must not enter the SQL mutation queue."
            ),
        )
        self.assertTrue(
            ProjectWriteService.queue_page_setting_if_sql(
                service,
                "database",
                "8",
                "bid_selected_page",
                ["22"],
            )
        )
        with self.assertRaisesRegex(ValueError, "Unsupported page setting"):
            PageSettingsPayload.from_updates(
                "bid_selected_page",
                [["8", "22"]],
            )

    def test_failed_view_state_outcomes_are_terminal_best_effort_persistence(self):
        callbacks = []
        logger = Mock()
        service = SimpleNamespace(
            uses_sql_collaboration_mutations=lambda _database_id: True,
            _active_bid_uid_for=lambda _database_id: "7",
            _sql_collaboration_provider=lambda: SimpleNamespace(
                is_resource_recovering=lambda *_args: False
            ),
            queue_page_settings=lambda *args, **_kwargs: (
                callbacks.append(args[4]) or 0
            ),
            logger=logger,
        )
        self.assertTrue(
            ProjectWriteService.queue_page_setting_if_sql(
                service,
                "database",
                "107",
                "view_state",
                [2.0, 10.0, 20.0],
            )
        )
        for outcome in (
            MutationOutcomeStatus.REJECTED,
            MutationOutcomeStatus.CONFLICT,
            MutationOutcomeStatus.FAILED_BEFORE_COMMIT,
            MutationOutcomeStatus.CANCELLED_BEFORE_START,
        ):
            callbacks[0](
                QueuedMutationResult(
                    database_id="database",
                    runtime_generation=1,
                    operation_id=str(uuid.uuid4()),
                    outcome_status=outcome,
                    message="Best-effort page-view persistence did not run.",
                )
            )
        logger.warning.assert_not_called()
        self.assertEqual(logger.debug.call_count, 4)

    def test_recovering_page_does_not_accumulate_best_effort_view_mutations(self):
        logger = Mock()
        queued = []
        service = SimpleNamespace(
            uses_sql_collaboration_mutations=lambda _database_id: True,
            _active_bid_uid_for=lambda _database_id: "7",
            _sql_collaboration_provider=lambda: SimpleNamespace(
                is_resource_recovering=lambda database_id, resource: (
                    database_id == "database"
                    and resource == ResourceRef("page", "107", 7)
                )
            ),
            queue_page_settings=lambda *args, **_kwargs: queued.append((args, kwargs)),
            logger=logger,
        )
        self.assertTrue(
            ProjectWriteService.queue_page_setting_if_sql(
                service,
                "database",
                "107",
                "view_state",
                [2.0, 10.0, 20.0],
            )
        )
        self.assertEqual(queued, [])
        logger.debug.assert_called_once()

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

    def test_recovered_operation_requires_matching_request_identity(self):
        request = DatabaseMutationRequest(
            database_id="database",
            session_id="session",
            operation_id=str(uuid.uuid4()),
            mutation_type=CollaborationMutationType.TAKEOFF_PLACEMENT.value,
            request_hash="1" * 64,
        )
        state = _SqlMutationState("database", object(), request)
        result = SqlProjectWriter._recovered_operation_result(
            state,
            (
                request.mutation_type,
                request.request_hash,
                1,
                '{"value":["100"],"value_available":true}',
            ),
        )
        self.assertEqual(result.outcome_status, MutationOutcomeStatus.COMMITTED)
        self.assertEqual(result.value, ["100"])
        with self.assertRaisesRegex(Exception, "reused with a different request"):
            SqlProjectWriter._recovered_operation_result(
                state,
                (request.mutation_type, "2" * 64, 1, "{}"),
            )

    def test_pending_operation_repository_round_trips_without_credentials(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "pending_sql_operations.json"
            repository = JsonPendingSqlOperationRepository(path)
            record = PendingSqlOperationRecord(
                database_id="database",
                operation_id=str(uuid.uuid4()),
                mutation_type=CollaborationMutationType.PLAN_ITEMS_DELETE,
                request_hash="a" * 64,
                owning_surface="main-plan",
                resources=(ResourceRef("takeoff", "10", 1),),
                dependency_resources=(ResourceRef("takeoffs_collection", "1", 1),),
                bid_uid=1,
                page_uid="20",
                state=PendingMutationState.UNCERTAIN,
            )
            repository.save(record)
            self.assertEqual(repository.list_all(), (record,))
            self.assertNotIn("password", path.read_text(encoding="utf-8").casefold())
            repository.save(replace(record, state=PendingMutationState.PROJECTING))
            self.assertEqual(
                repository.list_all()[0].state,
                PendingMutationState.PROJECTING,
            )
            with self.assertRaisesRegex(ValueError, "reused for another request"):
                repository.save(replace(record, database_id="other-database"))
            repository.remove(record.operation_id)
            self.assertEqual(repository.list_all(), ())

    def test_pending_operation_repository_rejects_noncanonical_records(self):
        operation_id = str(uuid.uuid4())
        canonical_record = {
            "database_id": "database",
            "operation_id": operation_id,
            "mutation_type": CollaborationMutationType.PLAN_ITEMS_DELETE.value,
            "request_hash": "a" * 64,
            "owning_surface": "main-plan",
            "resources": [
                {
                    "resource_type": "takeoff",
                    "resource_id": "10",
                    "bid_uid": 1,
                }
            ],
            "dependency_resources": [],
            "bid_uid": 1,
            "page_uid": "20",
            "state": PendingMutationState.UNCERTAIN.value,
        }
        invalid_documents = (
            {"operations": [canonical_record]},
            {"version": 0, "operations": [canonical_record]},
            {
                "version": 1,
                "operations": [
                    {
                        key: value
                        for key, value in canonical_record.items()
                        if key != "request_hash"
                    }
                ],
            },
            {
                "version": 1,
                "operations": [
                    {
                        **canonical_record,
                        "resources": [
                            {"resource_type": "takeoff", "resource_id": "10"}
                        ],
                    }
                ],
            },
            {
                "version": 1,
                "operations": [{**canonical_record, "page_uid": None}],
            },
            {
                "version": 1,
                "operations": [{**canonical_record, "bid_uid": "1"}],
            },
            {
                "version": 1,
                "operations": [
                    {
                        **canonical_record,
                        "resources": [
                            {
                                "resource_type": "takeoff",
                                "resource_id": 10,
                                "bid_uid": 1,
                            }
                        ],
                    }
                ],
            },
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "pending_sql_operations.json"
            repository = JsonPendingSqlOperationRepository(path)
            for document in invalid_documents:
                with self.subTest(document=document):
                    path.write_text(json.dumps(document), encoding="utf-8")
                    with self.assertRaises(ValueError):
                        repository.list_all()

    def test_recovered_paste_reconstructs_complete_authoritative_uid_maps(self):
        operation_id = str(uuid.uuid4())
        request = QueuedMutationRequest(
            database_id="database",
            operation_id=operation_id,
            mutation_type=CollaborationMutationType.PLAN_ITEMS_PASTE,
            owning_surface="main-plan",
            resources=(ResourceRef("takeoffs_collection", "7", 7),),
            bid_uid=7,
            page_uid="20",
            payload={"source": "clipboard"},
        )
        durable = DurableOperationResult(
            database_id="database",
            operation_id=operation_id,
            found=True,
            mutation_type=request.mutation_type.value,
            request_hash=request.request_hash,
            result_format_version=1,
            result_payload=(
                '{"value":{"annotation_uids":{"a":"200"},'
                '"condition_uids":{"c":"300"},'
                '"takeoff_uids":{"t":"100"}},"value_available":true}'
            ),
        )
        recovered = SqlCollaborationCoordinator._recovered_authoritative_result(
            request,
            durable,
        )
        self.assertEqual(recovered.created_resource_ids, ("100", "200"))
        self.assertEqual(
            dict(recovered.created_uid_maps),
            {
                "takeoffs": (("t", "100"),),
                "annotations": (("a", "200"),),
                "conditions": (("c", "300"),),
            },
        )
        self.assertEqual(recovered.affected_condition_uids, ("300",))

    def test_recovered_import_reconstructs_every_authoritative_identity_family(self):
        operation_id = str(uuid.uuid4())
        request = QueuedMutationRequest(
            database_id="database",
            operation_id=operation_id,
            mutation_type=CollaborationMutationType.PROJECT_IMPORT,
            owning_surface="project-import",
            resources=(ResourceRef("project_bids", "9"),),
            payload=ProjectImportPayload(
                source_path="C:/imports/project.ost",
                source_kind="ost",
                source_size=123,
                source_modified_ns=456,
                target_project_uid="9",
            ),
        )
        durable = DurableOperationResult(
            database_id="database",
            operation_id=operation_id,
            found=True,
            mutation_type=request.mutation_type.value,
            request_hash=request.request_hash,
            result_format_version=1,
            result_payload=json.dumps(
                {
                    "value": {
                        "project_uids": {"target": "9"},
                        "bid_uids": {"b": "10"},
                        "page_uids": {"p": "20"},
                        "condition_uids": {"c": "30"},
                        "layer_uids": {"l": "40"},
                        "area_uids": {"r": "50"},
                        "takeoff_uids": {"t": "60"},
                        "annotation_uids": {"a": "70"},
                    },
                    "value_available": True,
                },
                separators=(",", ":"),
                sort_keys=True,
            ),
        )
        recovered = SqlCollaborationCoordinator._recovered_authoritative_result(
            request, durable
        )
        self.assertEqual(recovered.affected_page_uids, ("20",))
        self.assertEqual(recovered.affected_condition_uids, ("30",))
        self.assertEqual(
            set(dict(recovered.created_uid_maps)),
            {
                "projects",
                "bids",
                "pages",
                "conditions",
                "layers",
                "areas",
                "takeoffs",
                "annotations",
            },
        )
        self.assertEqual(
            recovered.affected_families,
            (
                "hierarchy",
                "conditions",
                "areas",
                "pages",
                "layers",
                "takeoffs",
                "annotations",
                "cover_sheet",
                "master_data",
            ),
        )


if __name__ == "__main__":
    unittest.main()
