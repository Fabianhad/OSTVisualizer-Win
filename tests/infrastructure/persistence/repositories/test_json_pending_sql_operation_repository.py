import json
import tempfile
import unittest
import uuid
from dataclasses import replace
from pathlib import Path
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
from ost_visualizer.infrastructure.persistence.repositories.json_pending_sql_operation_repository import (
    JsonPendingSqlOperationRepository,
)


class PendingSqlOperationRepositoryTests(unittest.TestCase):
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
