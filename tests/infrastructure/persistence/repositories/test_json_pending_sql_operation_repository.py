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
            self.assertEqual(
                repository.list_all(),
                (replace(record, state=PendingMutationState.PROJECTING),),
            )
            repository.remove(record.operation_id)
            self.assertEqual(repository.list_all(), ())

    def test_pending_operation_repository_keeps_other_operations_and_orders_by_id(
        self,
    ):
        with tempfile.TemporaryDirectory() as directory:
            repository = JsonPendingSqlOperationRepository(
                Path(directory) / "pending_sql_operations.json"
            )
            records = [
                PendingSqlOperationRecord(
                    database_id="database",
                    operation_id=str(uuid.UUID(int=index)),
                    mutation_type=CollaborationMutationType.PLAN_ITEMS_DELETE,
                    request_hash="a" * 64,
                    owning_surface="main-plan",
                    resources=(ResourceRef("takeoff", str(index), 1),),
                    bid_uid=1,
                    page_uid="20",
                )
                for index in (3, 1, 2)
            ]
            for record in records:
                repository.save(record)
            self.assertEqual(
                repository.list_all(),
                tuple(sorted(records, key=lambda item: item.operation_id)),
            )
            repository.remove(records[0].operation_id)
            self.assertEqual(
                [item.operation_id for item in repository.list_all()],
                [records[1].operation_id, records[2].operation_id],
            )
            repository.remove(str(uuid.UUID(int=99)))
            self.assertEqual(len(repository.list_all()), 2)

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
            ({"operations": [canonical_record]}, "not canonical"),
            (
                {"version": 0, "operations": [canonical_record]},
                "unsupported version",
            ),
            (
                {"version": True, "operations": [canonical_record]},
                "unsupported version",
            ),
            (
                {"version": 1, "operations": [canonical_record], "extra": 1},
                "not canonical",
            ),
            ({"version": 1, "operations": {}}, "must contain a list"),
            ({"version": 1, "operations": ["not-an-object"]}, "must be objects"),
            (
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
                "entries are not canonical",
            ),
            (
                {
                    "version": 1,
                    "operations": [{**canonical_record, "unexpected": "value"}],
                },
                "entries are not canonical",
            ),
            (
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
                "resources are not canonical",
            ),
            (
                {
                    "version": 1,
                    "operations": [{**canonical_record, "page_uid": None}],
                },
                "page_uid must be a string",
            ),
            (
                {
                    "version": 1,
                    "operations": [{**canonical_record, "bid_uid": "1"}],
                },
                "bid_uid must be an integer",
            ),
            (
                {
                    "version": 1,
                    "operations": [{**canonical_record, "bid_uid": True}],
                },
                "bid_uid must be an integer",
            ),
            (
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
                "resource identities must be strings",
            ),
            (
                {
                    "version": 1,
                    "operations": [
                        {
                            **canonical_record,
                            "dependency_resources": [
                                {
                                    "resource_type": "takeoff",
                                    "resource_id": "10",
                                    "bid_uid": "1",
                                }
                            ],
                        }
                    ],
                },
                "resource bid_uid must be an integer",
            ),
            (
                {
                    "version": 1,
                    "operations": [{**canonical_record, "mutation_type": "unknown"}],
                },
                "is not a valid CollaborationMutationType",
            ),
            (
                {
                    "version": 1,
                    "operations": [{**canonical_record, "state": "finished"}],
                },
                "is not a valid PendingMutationState",
            ),
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "pending_sql_operations.json"
            repository = JsonPendingSqlOperationRepository(path)
            path.write_text(
                json.dumps({"version": 1, "operations": [canonical_record]}),
                encoding="utf-8",
            )
            self.assertEqual(
                [item.operation_id for item in repository.list_all()], [operation_id]
            )
            for document, message in invalid_documents:
                with self.subTest(document=document):
                    path.write_text(json.dumps(document), encoding="utf-8")
                    with self.assertRaisesRegex(ValueError, message):
                        repository.list_all()
            path.write_text("{broken", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "Invalid JSON"):
                repository.list_all()

    def test_pending_operation_repository_never_overwrites_a_noncanonical_file(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "pending_sql_operations.json"
            repository = JsonPendingSqlOperationRepository(path)
            path.write_text(
                json.dumps({"version": 2, "operations": []}), encoding="utf-8"
            )
            before = path.read_bytes()
            record = PendingSqlOperationRecord(
                database_id="database",
                operation_id=str(uuid.uuid4()),
                mutation_type=CollaborationMutationType.PLAN_ITEMS_DELETE,
                request_hash="a" * 64,
                owning_surface="main-plan",
                resources=(ResourceRef("takeoff", "10", 1),),
            )
            with self.assertRaisesRegex(ValueError, "unsupported version"):
                repository.save(record)
            with self.assertRaisesRegex(ValueError, "unsupported version"):
                repository.remove(record.operation_id)
            self.assertEqual(path.read_bytes(), before)
