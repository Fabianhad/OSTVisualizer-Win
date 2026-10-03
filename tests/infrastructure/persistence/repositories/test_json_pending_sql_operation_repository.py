import json
import tempfile
import threading
import unittest
import uuid
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch
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


def _pending_record(**overrides):
    values = dict(
        database_id="database",
        operation_id=str(uuid.UUID(int=1)),
        mutation_type=CollaborationMutationType.PLAN_ITEMS_DELETE,
        request_hash="a" * 64,
        owning_surface="main-plan",
        resources=(ResourceRef("takeoff", "10", 1),),
        dependency_resources=(ResourceRef("takeoffs_collection", "1", 1),),
        bid_uid=1,
        page_uid="20",
        state=PendingMutationState.UNCERTAIN,
    )
    values.update(overrides)
    return PendingSqlOperationRecord(**values)


class PendingSqlOperationRepositoryDurabilityTests(unittest.TestCase):
    """Second pass: identity guard, canonical parsing and crash-safe writes."""

    def _repository(self, directory):
        path = Path(directory) / "pending_sql_operations.json"
        return path, JsonPendingSqlOperationRepository(path)

    def test_default_location_is_the_app_data_pending_operations_file(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch(
                "ost_visualizer.infrastructure.persistence.repositories."
                "json_pending_sql_operation_repository.get_app_data_dir",
                return_value=Path(directory),
            ):
                repository = JsonPendingSqlOperationRepository()
            record = _pending_record()
            repository.save(record)
            stored = json.loads(
                (Path(directory) / "pending_sql_operations.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(
                [item["operation_id"] for item in stored["operations"]],
                [record.operation_id],
            )
            self.assertEqual(sorted(stored), ["operations", "version"])

    def test_missing_optional_bid_identities_round_trip_as_null(self):
        with tempfile.TemporaryDirectory() as directory:
            path, repository = self._repository(directory)
            record = _pending_record(
                resources=(ResourceRef("database", "OSTV", None),),
                dependency_resources=(ResourceRef("bid", "4", None),),
                bid_uid=None,
            )
            repository.save(record)
            self.assertEqual(repository.list_all(), (record,))
            stored = json.loads(path.read_text(encoding="utf-8"))["operations"][0]
            self.assertIsNone(stored["bid_uid"])
            self.assertIsNone(stored["resources"][0]["bid_uid"])
            self.assertIsNone(stored["dependency_resources"][0]["bid_uid"])

    def test_reusing_an_operation_id_for_any_other_request_field_is_rejected(self):
        original = _pending_record()
        different_requests = {
            "database_id": {"database_id": "other-database"},
            "mutation_type": {"mutation_type": CollaborationMutationType.PLAN_GEOMETRY},
            "request_hash": {"request_hash": "b" * 64},
            "owning_surface": {"owning_surface": "other-surface"},
            "resources": {"resources": (ResourceRef("takeoff", "11", 1),)},
            "dependency_resources": {
                "dependency_resources": (ResourceRef("takeoffs_collection", "2", 1),)
            },
            "bid_uid": {"bid_uid": 2},
            "page_uid": {"page_uid": "21"},
        }
        with tempfile.TemporaryDirectory() as directory:
            path, repository = self._repository(directory)
            repository.save(original)
            before = path.read_bytes()
            for field, change in different_requests.items():
                with self.subTest(field=field):
                    with self.assertRaisesRegex(ValueError, "reused for another"):
                        repository.save(_pending_record(**change))
                    self.assertEqual(path.read_bytes(), before)
            # Only the state may move for the same request (the lifecycle).
            for state in PendingMutationState:
                repository.save(replace(original, state=state))
                self.assertEqual(repository.list_all()[0].state, state)

    def test_non_object_documents_and_entries_are_rejected_as_not_canonical(self):
        resource_keys = ["resource_type", "resource_id", "bid_uid"]
        record = {
            "database_id": "database",
            "operation_id": str(uuid.UUID(int=1)),
            "mutation_type": CollaborationMutationType.PLAN_ITEMS_DELETE.value,
            "request_hash": "a" * 64,
            "owning_surface": "main-plan",
            "resources": [
                {"resource_type": "takeoff", "resource_id": "10", "bid_uid": None}
            ],
            "dependency_resources": [],
            "bid_uid": None,
            "page_uid": "",
            "state": PendingMutationState.QUEUED.value,
        }
        documents = (
            ([], "not canonical"),
            (["version", "operations"], "not canonical"),
            ([{"version": 1}], "not canonical"),
            (None, "not canonical"),
            ("text", "not canonical"),
            (7, "not canonical"),
            (
                {"version": 1, "operations": [{**record, "resources": ["x"]}]},
                "resources are not canonical",
            ),
            (
                {
                    "version": 1,
                    "operations": [{**record, "resources": [resource_keys]}],
                },
                "resources are not canonical",
            ),
            (
                {
                    "version": 1,
                    "operations": [
                        {
                            **record,
                            "resources": [
                                {
                                    "resource_type": 5,
                                    "resource_id": "10",
                                    "bid_uid": None,
                                }
                            ],
                        }
                    ],
                },
                "resource identities must be strings",
            ),
            (
                {"version": 1, "operations": [{**record, "resources": {}}]},
                "resources must be a list",
            ),
        )
        with tempfile.TemporaryDirectory() as directory:
            path, repository = self._repository(directory)
            path.write_text(
                json.dumps({"version": 1, "operations": [record]}), encoding="utf-8"
            )
            self.assertEqual(len(repository.list_all()), 1)
            for document, message in documents:
                with self.subTest(document=document):
                    path.write_text(json.dumps(document), encoding="utf-8")
                    with self.assertRaisesRegex(ValueError, message):
                        repository.list_all()

    def test_corrupt_or_truncated_files_are_reported_and_never_overwritten(self):
        record = _pending_record()
        good = json.dumps({"version": 1, "operations": []}, indent=2)
        corrupt_files = {
            "empty": b"",
            "truncated": good[: len(good) // 2].encode("utf-8"),
            "not-utf8": b"\xff\xfe\x00{",
            "trailing-garbage": (good + "}").encode("utf-8"),
        }
        with tempfile.TemporaryDirectory() as directory:
            path, repository = self._repository(directory)
            for label, content in corrupt_files.items():
                with self.subTest(file=label):
                    path.write_bytes(content)
                    with self.assertRaises(ValueError):
                        repository.list_all()
                    with self.assertRaises(ValueError):
                        repository.save(record)
                    with self.assertRaises(ValueError):
                        repository.remove(record.operation_id)
                    self.assertEqual(path.read_bytes(), content)
                    self.assertEqual(
                        [item.name for item in Path(directory).iterdir()],
                        [path.name],
                    )

    def test_failed_rename_keeps_the_previous_file_and_leaves_no_temp_file(self):
        original = _pending_record()
        newer = _pending_record(
            operation_id=str(uuid.UUID(int=2)),
            resources=(ResourceRef("takeoff", "11", 1),),
        )
        with tempfile.TemporaryDirectory() as directory:
            path, repository = self._repository(directory)
            repository.save(original)
            before = path.read_bytes()
            with patch.object(
                Path, "replace", side_effect=PermissionError("rename blocked")
            ):
                with self.assertLogs(repository.logger, level="ERROR"):
                    with self.assertRaisesRegex(PermissionError, "rename blocked"):
                        repository.save(newer)
                with self.assertLogs(repository.logger, level="ERROR"):
                    with self.assertRaises(PermissionError):
                        repository.remove(original.operation_id)
            self.assertEqual(path.read_bytes(), before)
            self.assertEqual(repository.list_all(), (original,))
            self.assertEqual(
                [item.name for item in Path(directory).iterdir()], [path.name]
            )
            repository.save(newer)
            self.assertEqual(repository.list_all(), (original, newer))

    def test_failed_flush_to_disk_never_publishes_a_partial_file(self):
        original = _pending_record()
        newer = _pending_record(
            operation_id=str(uuid.UUID(int=2)),
            resources=(ResourceRef("takeoff", "11", 1),),
        )
        with tempfile.TemporaryDirectory() as directory:
            path, repository = self._repository(directory)
            repository.save(original)
            before = path.read_bytes()
            with patch("os.fsync", side_effect=OSError(28, "No space left on device")):
                with self.assertLogs(repository.logger, level="ERROR"):
                    with self.assertRaises(OSError):
                        repository.save(newer)
            self.assertEqual(path.read_bytes(), before)
            self.assertEqual(
                [item.name for item in Path(directory).iterdir()], [path.name]
            )
            self.assertEqual(repository.list_all(), (original,))

    def test_orphaned_temp_file_from_a_crash_is_never_replayed(self):
        stranded = _pending_record(operation_id=str(uuid.UUID(int=9)))
        saved = _pending_record(operation_id=str(uuid.UUID(int=1)))
        with tempfile.TemporaryDirectory() as directory:
            path, repository = self._repository(directory)
            writer = JsonPendingSqlOperationRepository(
                Path(directory) / "elsewhere.json"
            )
            writer.save(stranded)
            orphan = Path(directory) / f".{path.name}.0123456789abcdef.tmp"
            orphan.write_bytes((Path(directory) / "elsewhere.json").read_bytes())
            half_written = Path(directory) / f".{path.name}.fedcba9876543210.tmp"
            half_written.write_bytes(b'{"version": 1, "operations": [{"data')
            self.assertEqual(repository.list_all(), ())
            repository.save(saved)
            self.assertEqual(repository.list_all(), (saved,))
            repository.remove(saved.operation_id)
            self.assertEqual(repository.list_all(), ())
            self.assertTrue(orphan.exists())
            self.assertTrue(half_written.exists())

    def test_concurrent_writers_never_lose_an_update(self):
        first = _pending_record(operation_id=str(uuid.UUID(int=1)))
        second = _pending_record(operation_id=str(uuid.UUID(int=2)))
        with tempfile.TemporaryDirectory() as directory:
            _path, repository = self._repository(directory)
            original_save = repository._save_json
            inside_first_save = threading.Event()
            release_first_save = threading.Event()
            calls = []

            def pausing_save(data):
                calls.append(data)
                if len(calls) == 1:
                    inside_first_save.set()
                    release_first_save.wait(timeout=5.0)
                original_save(data)

            repository._save_json = pausing_save
            first_thread = threading.Thread(target=repository.save, args=(first,))
            second_thread = threading.Thread(target=repository.save, args=(second,))
            first_thread.start()
            self.assertTrue(inside_first_save.wait(timeout=5.0))
            second_thread.start()
            second_thread.join(timeout=0.2)
            # The second writer must be waiting for the first one's whole
            # load-modify-save cycle, not interleaving its own.
            self.assertTrue(second_thread.is_alive())
            release_first_save.set()
            first_thread.join(timeout=5.0)
            second_thread.join(timeout=5.0)
            self.assertFalse(first_thread.is_alive() or second_thread.is_alive())
            self.assertEqual(repository.list_all(), (first, second))

    def test_many_concurrent_savers_and_removers_leave_a_consistent_file(self):
        records = [
            _pending_record(
                operation_id=str(uuid.UUID(int=index)),
                resources=(ResourceRef("takeoff", str(index), 1),),
            )
            for index in range(1, 25)
        ]
        with tempfile.TemporaryDirectory() as directory:
            _path, repository = self._repository(directory)
            start = threading.Barrier(len(records))
            errors = []

            def work(record):
                try:
                    start.wait(timeout=5.0)
                    repository.save(record)
                    if int(record.operation_id[-4:], 16) % 2 == 0:
                        repository.remove(record.operation_id)
                except BaseException as exc:  # pragma: no cover - failure path
                    errors.append(exc)

            threads = [threading.Thread(target=work, args=(item,)) for item in records]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(timeout=10.0)
            self.assertEqual(errors, [])
            expected = tuple(
                item for item in records if int(item.operation_id[-4:], 16) % 2 == 1
            )
            self.assertEqual(repository.list_all(), expected)
