"""Application write orchestration; deterministic ports, no live database or Qt UI."""

import json
import logging
import unittest
import uuid
from contextlib import nullcontext
from copy import deepcopy
from dataclasses import asdict, replace
from types import SimpleNamespace
from unittest.mock import Mock, patch
from ost_visualizer.application.dtos.active_bid_locked_error import (
    ActiveBidLockedError,
)
from ost_visualizer.application.dtos.collaboration_dtos import (
    AuthoritativeMutationResult,
    ChangeOperation,
    CollaborationMutationType,
    ConcurrencyToken,
    DatabaseMutationResult,
    EditLeaseHandle,
    ExpectedResourceVersion,
    MutationExecutionResult,
    MutationOutcomeStatus,
    PlanItemsPastePayload,
    PlanPropertyPayload,
    ProjectImportPayload,
    ProjectWritePayload,
    QueuedMutationRequest,
    QueuedMutationResult,
    ResourceRef,
    SynchronizationConflict,
    SynchronizationConflictKind,
)
from ost_visualizer.application.dtos.collaboration_resource_catalog import (
    annotation_resource_id,
)
from ost_visualizer.application.dtos.condition_takeoff_reassignment import (
    ConditionTakeoffReassignment,
)
from ost_visualizer.application.dtos.create_condition_spec_dto import (
    CreateConditionSpec,
)
from ost_visualizer.application.dtos.insert_annotation_spec_dto import (
    InsertAnnotationSpec,
)
from ost_visualizer.application.dtos.insert_takeoff_spec_dto import InsertTakeoffSpec
from ost_visualizer.application.dtos.update_condition_dto import (
    UpdateConditionDto,
    UpdateConditionResultDto,
)
from ost_visualizer.application.dtos.write_reload_result import WriteReloadResult
from ost_visualizer.application.events.app_events import AppEvents
from ost_visualizer.application.interfaces.i_mdb_connection_manager import (
    DatabaseConnectionUnavailableError,
)
from ost_visualizer.application.services.project_write_service import (
    BatchWriteResult,
    DeleteValidationResult,
    ProjectWriteService,
)
from ost_visualizer.application.services.active_bid_write_guard import (
    ActiveBidWriteGuard,
)
from ost_visualizer.application.use_cases.project.save_page_scale_use_case import (
    SavePageScaleUseCase,
)
from ost_visualizer.domain.aggregates.ost_aggregate import OstAggregate
from ost_visualizer.domain.entities.area import BidArea, BidAreaChangeset
from ost_visualizer.domain.entities.bid import Bid
from ost_visualizer.domain.entities.condition import Condition
from ost_visualizer.domain.entities.condition_folder import BidConditionFolder
from ost_visualizer.domain.entities.employee import Employee
from ost_visualizer.domain.entities.identity_refs import BidRef
from ost_visualizer.domain.entities.page import Page
from ost_visualizer.domain.entities.takeoff import Takeoff
from ost_visualizer.domain.services.project_data_service import ProjectDataService
from ost_visualizer.infrastructure.events.event_bus import EventBus
from tests.application.services.write_access_support import (
    _CapabilityService as _access__CapabilityService,
    _ConcurrencyTokens as _access__ConcurrencyTokens,
    _EventBus as _access__EventBus,
    _MutationExecutor as _access__MutationExecutor,
    _SessionRegistry as _access__SessionRegistry,
)
from tests.application.services.write_permission_support import (
    _DatabaseCapability as _permissions__DatabaseCapability,
    _EventBus as _permissions__EventBus,
    _ProjectData as _permissions__ProjectData,
    _SequenceUseCase as _permissions__SequenceUseCase,
    _UseCase as _permissions__UseCase,
    _write_service as _permissions__write_service,
)
from tests.helpers.annotation_geometry import ANNOTATION_POSITIONS


class _SequenceUseCase:
    def __init__(self, *results) -> None:
        self.results = list(results)
        self.calls = []

    def execute(self, *args):
        self.calls.append(args)
        result = self.results.pop(0)
        if isinstance(result, BaseException):
            raise result
        return result

    def execute_default(self, *args):
        return self.execute(*args)


class _Recorder:
    def __init__(self):
        self.records = []

    def record(self, resource, operation, *, changed_fields=(), payload=""):
        self.records.append((resource, operation, tuple(changed_fields), payload))


class _CapturedQueueProvider:
    def __init__(self) -> None:
        self.requests = []
        self.options = []

    def uses_sql_collaboration(self, _database_id: str) -> bool:
        return True

    def queue_request(self, request, execute, callback, **options):
        self.requests.append((request, execute, callback))
        self.options.append(options)
        return 41


class ProjectWriteServiceCollaborationTests(unittest.TestCase):
    def test_project_write_queues_takeoff_insert_with_page_and_condition_dependencies(
        self,
    ):
        queued = []

        class _MutationQueue:
            def queue_request(self, *args, **kwargs):
                queued.append((args, kwargs))
                return 7

        service = ProjectWriteService.__new__(ProjectWriteService)
        service._sql_collaboration_provider = lambda: _MutationQueue()
        insert_calls = []
        service._insert_takeoffs_mutation = lambda *_args, **kwargs: (
            insert_calls.append(kwargs)
            or DatabaseMutationResult(
                operation_id=kwargs["operation_id"],
                outcome_status=MutationOutcomeStatus.COMMITTED,
                value=["501", "502"],
            )
        )
        callback = lambda _result: None
        specs = [
            InsertTakeoffSpec(
                condition_uid="10",
                page_uid="20",
                area_uid="30",
                position=[1.0, 2.0],
                parent_uid="40",
            ),
            InsertTakeoffSpec(
                condition_uid="11",
                page_uid="20",
                area_uid=None,
                position=[3.0, 4.0],
            ),
        ]
        generation = service.queue_takeoff_placement(
            "database",
            "8",
            specs,
            "7b3c5ac1-e623-44aa-8203-26a0125873b9",
            callback,
        )
        args, kwargs = queued[0]
        request = args[0]
        self.assertEqual(len(queued), 1)
        self.assertEqual(insert_calls, [])
        self.assertIsInstance(request, QueuedMutationRequest)
        self.assertEqual(request.database_id, "database")
        self.assertEqual(
            request.mutation_type, CollaborationMutationType.TAKEOFF_PLACEMENT
        )
        self.assertEqual(
            request.resources, (ResourceRef("takeoffs_collection", "8", 8),)
        )
        work_result = args[1]()
        self.assertEqual(
            work_result.outcome_status,
            MutationOutcomeStatus.COMMITTED,
        )
        self.assertEqual(work_result.created_resource_ids, ("501", "502"))
        self.assertEqual(work_result.authoritative_result.affected_page_uids, ("20",))
        self.assertEqual(
            work_result.authoritative_result.affected_condition_uids, ("10", "11")
        )
        self.assertIs(args[2], callback)
        self.assertEqual(
            request.dependency_resources,
            (
                ResourceRef("area", "30", 8),
                ResourceRef("condition", "10", 8),
                ResourceRef("condition", "11", 8),
                ResourceRef("page", "20", 8),
                ResourceRef("takeoff", "40", 8),
            ),
        )
        self.assertEqual(kwargs["result_validator"](work_result), "")
        self.assertEqual(
            kwargs["result_validator"](
                replace(work_result, created_resource_ids=("501",))
            ),
            "The SQL mutation returned an incomplete authoritative identity set.",
        )
        self.assertNotIn("allow_resource_overlap", kwargs)
        self.assertEqual(generation, 7)
        self.assertEqual(
            insert_calls[0]["consistency_resources"],
            request.dependency_resources,
        )
        self.assertFalse(insert_calls[0]["publish_conflict_event"])
        self.assertEqual(insert_calls[0]["operation_id"], request.operation_id)
        self.assertEqual(insert_calls[0]["request_hash"], request.request_hash)

    def test_queued_takeoff_reassign_rejects_missing_member_before_bulk_update(self):
        from ost_visualizer.application.dtos.collaboration_dtos import (
            ExpectedResourceVersion,
        )

        queued = []

        class MutationQueue:
            def queue_request(self, *args, **kwargs):
                queued.append((args, kwargs))
                return 9

        class MutationExecutor:
            def __init__(self):
                self.verifications = []

            def verify_plan_items_exist(
                self,
                database_id,
                bid_uid,
                takeoff_uids,
                annotations,
                *,
                takeoff_ownership=(),
            ):
                self.verifications.append(
                    (database_id, bid_uid, tuple(takeoff_uids), tuple(annotations))
                )
                raise RuntimeError("selected takeoff was deleted")

        executor = MutationExecutor()
        save_calls = []
        service = ProjectWriteService.__new__(ProjectWriteService)
        service._sql_collaboration_provider = lambda: MutationQueue()
        service._bid_write_guard = SimpleNamespace(
            blocks_active_locked_bid_write=lambda _database_id, _bid_uid: False
        )
        service._project_data = SimpleNamespace(
            get_current_bid_ref=lambda: BidRef("database", "8"),
            get_all_takeoffs=lambda: [
                Takeoff(uid=uid, page_uid="30", condition_uid="20")
                for uid in ("101", "102")
            ],
        )
        service._mutation_executor = executor
        service._save_takeoffs_condition = SimpleNamespace(
            execute=lambda *_args: save_calls.append(_args) or True
        )

        def execute_mutation(
            _database_id,
            _resources,
            operation,
            **_kwargs,
        ):
            value = operation(SimpleNamespace(record=lambda *_args, **_kwargs: None))
            return DatabaseMutationResult(
                operation_id=str(uuid.uuid4()),
                outcome_status=MutationOutcomeStatus.COMMITTED,
                value=value,
            )

        service._execute_database_mutation = execute_mutation
        service._concurrency_tokens = SimpleNamespace(
            expected_versions=lambda _database, resources: tuple(
                ExpectedResourceVersion(resource, ConcurrencyToken(b"a" * 8))
                for resource in resources
            )
        )
        service.queue_plan_properties(
            "database",
            "8",
            "takeoff_condition",
            [("101", "20"), ("102", "20")],
            lambda _result: None,
            page_uids=("30",),
            dependency_resources=(ResourceRef("condition", "20", 8),),
        )
        with self.assertRaisesRegex(RuntimeError, "selected takeoff was deleted"):
            queued[0][0][1]()
        self.assertEqual(
            executor.verifications,
            [("database", "8", ("101", "102"), ())],
        )
        self.assertEqual(save_calls, [])

    def test_queued_bulk_move_rejects_missing_member_before_geometry_update(self):
        queued = []

        class MutationQueue:
            def queue_request(self, *args, **kwargs):
                queued.append((args, kwargs))
                return 10

        class MutationExecutor:
            def __init__(self):
                self.verifications = []

            def verify_plan_items_exist(
                self, database_id, bid_uid, takeoff_uids, annotations
            ):
                self.verifications.append(
                    (database_id, bid_uid, tuple(takeoff_uids), tuple(annotations))
                )
                raise RuntimeError("selected plan item was deleted")

        executor = MutationExecutor()
        save_calls = []
        service = ProjectWriteService.__new__(ProjectWriteService)
        service._sql_collaboration_provider = lambda: MutationQueue()
        service._bid_write_guard = SimpleNamespace(
            blocks_active_locked_bid_write=lambda _database_id, _bid_uid: False
        )
        service._mutation_executor = executor
        service._save_takeoff_positions = SimpleNamespace(
            execute=lambda *_args: save_calls.append(_args) or True
        )
        service._save_takeoff_rotations = SimpleNamespace(
            execute=lambda *_args: save_calls.append(_args) or True
        )
        service._save_annotation_positions = SimpleNamespace(
            execute=lambda *_args: save_calls.append(_args) or True
        )

        def execute_mutation(
            _database_id,
            _resources,
            operation,
            **_kwargs,
        ):
            value = operation(SimpleNamespace(record=lambda *_args, **_kwargs: None))
            return DatabaseMutationResult(
                operation_id=str(uuid.uuid4()),
                outcome_status=MutationOutcomeStatus.COMMITTED,
                value=value,
            )

        service._execute_database_mutation = execute_mutation
        service.queue_plan_geometry(
            "database",
            "8",
            lambda _result: None,
            takeoff_positions=[
                ("101", [1.0, 2.0]),
                ("102", [3.0, 4.0]),
            ],
            annotation_positions=[("201", "line", [5.0, 6.0, 7.0, 8.0])],
            page_uids=("30",),
        )
        with self.assertRaisesRegex(RuntimeError, "selected plan item was deleted"):
            queued[0][0][1]()
        self.assertEqual(
            executor.verifications,
            [("database", "8", ("101", "102"), (("201", "line"),))],
        )
        self.assertEqual(save_calls, [])

    def test_takeoff_insert_rejects_incomplete_identities_before_commit(self):
        service = ProjectWriteService.__new__(ProjectWriteService)
        service._bid_write_guard = SimpleNamespace(
            blocks_active_locked_bid_write=lambda _database_id, _bid_uid: False
        )
        service._insert_takeoffs = SimpleNamespace(
            execute=lambda _database_id, _bid_uid, _specs: ["501"]
        )
        specs = [
            InsertTakeoffSpec(
                condition_uid="10",
                page_uid="20",
                area_uid=None,
                position=[1.0, 2.0],
            ),
            InsertTakeoffSpec(
                condition_uid="10",
                page_uid="20",
                area_uid=None,
                position=[3.0, 4.0],
            ),
        ]

        class RejectingRecorder:
            def record(
                self,
                _resource,
                _operation,
                *,
                changed_fields=(),
                payload="",
            ):
                del changed_fields, payload
                self.fail("an incomplete identity batch must not be recorded")

            def fail(self, message):
                raise AssertionError(message)

        def execute_mutation(
            _database_id,
            _resources,
            operation,
            *,
            operation_id="",
            mutation_type=CollaborationMutationType.PROJECT_WRITE.value,
            request_hash="",
            result_format_version=1,
            block_bid_child_locks=False,
            block_bid_active_editors=False,
            publish_conflict_event=True,
        ):
            del (
                operation_id,
                mutation_type,
                request_hash,
                result_format_version,
                block_bid_child_locks,
                block_bid_active_editors,
                publish_conflict_event,
            )
            return operation(RejectingRecorder())

        service._execute_database_mutation = execute_mutation
        with self.assertRaisesRegex(RuntimeError, "authoritative identity set"):
            service._insert_takeoffs_mutation("database", "8", specs)

    def test_empty_takeoff_inserts_do_not_create_mutation_requests(self):
        service = ProjectWriteService.__new__(ProjectWriteService)

        def reject_local_mutation(
            _database_id,
            _bid_uid,
            _specs,
            *,
            consistency_resources=(),
            publish_conflict_event=True,
            operation_id="",
            request_hash="",
        ):
            del (
                consistency_resources,
                publish_conflict_event,
                operation_id,
                request_hash,
            )
            self.fail("an empty insert must not enter the mutation boundary")

        service._insert_takeoffs_mutation = reject_local_mutation
        self.assertEqual(service.insert_takeoffs("database", "8", []), [])
        with self.assertRaisesRegex(ValueError, "requires at least one takeoff"):
            service.queue_takeoff_placement(
                "database",
                "8",
                [],
                "7b3c5ac1-e623-44aa-8203-26a0125873b9",
                lambda _result: None,
            )


class ProjectWriteDeferredBoundaryTests(unittest.TestCase):
    def test_project_write_service_reports_ost_active_as_expected_deferred_block(self):
        service = ProjectWriteService.__new__(ProjectWriteService)
        service._database_capability_service = SimpleNamespace(
            is_editable=lambda _locator, resource=None: True
        )
        service._connection_manager = SimpleNamespace(is_write_blocked=lambda: True)
        service._bid_write_guard = SimpleNamespace(
            is_active_locked_bid_write_blocked=lambda _file_path, bid_uid=None: False
        )
        self.assertTrue(service.is_expected_deferred_write_blocked("a.mdb"))
        service._connection_manager.is_write_blocked = lambda: False
        self.assertFalse(service.is_expected_deferred_write_blocked("a.mdb"))

    def test_project_write_service_reports_locked_bid_as_expected_deferred_block(self):
        service = ProjectWriteService.__new__(ProjectWriteService)
        service._database_capability_service = SimpleNamespace(
            is_editable=lambda _locator, resource=None: True
        )
        service._connection_manager = SimpleNamespace(is_write_blocked=lambda: False)
        service._bid_write_guard = SimpleNamespace(
            is_active_locked_bid_write_blocked=lambda db_path, bid_uid=None: (
                db_path,
                bid_uid,
            )
            == ("a.mdb", None)
        )
        self.assertTrue(service.is_expected_deferred_write_blocked("a.mdb"))
        self.assertFalse(service.is_expected_deferred_write_blocked("other.mdb"))

    def test_page_area_write_can_skip_database_refresh(self):
        data = _permissions__ProjectData()
        events = _permissions__EventBus()
        service, *_ = _permissions__write_service(data, event_bus=events)
        service._save_page_area = _permissions__UseCase(True)
        service._reload_database = Mock(return_value=True)
        database = data.bid_ref.file_path
        self.assertTrue(
            service.save_page_area(
                database, "p1", "2", publish_database_refreshed_after_write=False
            )
        )
        self.assertEqual(service._save_page_area.calls, [((database, "p1", "2"), {})])
        service._reload_database.assert_not_called()
        self.assertEqual(events.published, [])
        # Positive control exercises the same real reload policy with its default.
        self.assertTrue(service.save_page_area(database, "p1", "3"))
        self.assertEqual(
            service._save_page_area.calls,
            [((database, "p1", "2"), {}), ((database, "p1", "3"), {})],
        )
        service._reload_database.assert_called_once_with(database)
        self.assertEqual(
            events.published,
            [
                (
                    AppEvents.DATABASE_REFRESHED,
                    {
                        "file_path": database,
                        "image_sources_unchanged": False,
                        "mesh_scene_unchanged": False,
                        "page_scale_uids": (),
                    },
                )
            ],
        )


class ProjectWriteQueueContractTests(unittest.TestCase):
    def test_queued_project_failures_preserve_outcome_without_success_projection(self):
        for status, attempted in (
            (MutationOutcomeStatus.FAILED_BEFORE_COMMIT, False),
            (MutationOutcomeStatus.CONFLICT, False),
            (MutationOutcomeStatus.COMMIT_STATUS_UNKNOWN, True),
        ):
            with self.subTest(status=status):
                service, provider = MdbSqlBehaviorParityTests._queued_project_service()
                completed = []
                service.queue_project_create("database", "Project", completed.append)
                request, execute, _callback = provider.requests[0]
                conflict = (
                    SynchronizationConflict(
                        "database", request.resources[0], "Version changed"
                    )
                    if status == MutationOutcomeStatus.CONFLICT
                    else None
                )
                mutation = DatabaseMutationResult(
                    operation_id=request.operation_id,
                    outcome_status=status,
                    conflict=conflict,
                    commit_attempted=attempted,
                    consumed_lock_tokens=("consumed-lease",) if attempted else (),
                )
                service._execute_database_mutation = Mock(return_value=mutation)
                result = execute()
                self.assertEqual(result.outcome_status, status)
                self.assertIs(result.conflict, conflict)
                self.assertEqual(result.commit_attempted, attempted)
                self.assertEqual(
                    result.consumed_lock_tokens, mutation.consumed_lock_tokens
                )
                self.assertEqual(result.created_resource_ids, ())
                self.assertIsNone(result.authoritative_result)
                self.assertEqual(
                    result.message,
                    (
                        "Version changed"
                        if conflict
                        else "The database rejected the project update."
                    ),
                )
                service._execute_database_mutation.assert_called_once()
                self.assertEqual(service._create_project.calls, [])
                self.assertEqual(completed, [])

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
        mutation_calls = []
        import_calls = []

        def execute_mutation(database, resources, operation, **options):
            recorder = _Recorder()
            mutation_calls.append((database, resources, options))
            return DatabaseMutationResult(
                operation_id=captured["request"].operation_id,
                outcome_status=MutationOutcomeStatus.COMMITTED,
                value=operation(recorder),
                commit_attempted=True,
            )

        def import_work(recorder):
            import_calls.append(recorder)
            return value

        service._execute_database_mutation = execute_mutation
        completed = []
        sequence = service.queue_project_import(
            "database", "9", payload, import_work, completed.append
        )
        self.assertEqual(import_calls, [])
        self.assertEqual(mutation_calls, [])
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
        self.assertEqual(len(import_calls), 1)
        self.assertEqual(len(mutation_calls), 1)
        request = captured["request"]
        self.assertEqual(request.dependency_resources, (ResourceRef("project", "9"),))
        self.assertEqual(mutation_calls[0][0], "database")
        self.assertEqual(
            mutation_calls[0][1],
            tuple(sorted({*request.resources, *request.dependency_resources})),
        )
        self.assertEqual(mutation_calls[0][2]["request_hash"], request.request_hash)
        self.assertFalse(mutation_calls[0][2]["publish_conflict_event"])
        self.assertEqual(
            dict(execution.authoritative_result.created_uid_maps),
            {
                "projects": (("target", "9"),),
                "bids": (("b", "10"),),
                "pages": (("p", "20"),),
                "conditions": (("c", "30"),),
                "layers": (("l", "40"),),
                "areas": (("r", "50"),),
                "takeoffs": (("t", "60"),),
                "annotations": (("a", "70"),),
            },
        )
        self.assertEqual(completed, [])
        terminal = QueuedMutationResult(
            database_id="database",
            runtime_generation=1,
            operation_id=request.operation_id,
            outcome_status=execution.outcome_status,
            authoritative_result=execution.authoritative_result,
            commit_attempted=True,
        )
        captured["callback"](terminal)
        self.assertEqual(completed, [terminal])

    def test_client_page_state_kinds_are_rejected_by_sql_mutation_queue(self):
        service = SimpleNamespace(
            uses_sql_collaboration_mutations=lambda _database_id: True,
        )
        for setting_kind in ("bid_selected_page", "view_state"):
            with self.subTest(setting_kind=setting_kind):
                with self.assertRaisesRegex(ValueError, "must not enter the SQL queue"):
                    ProjectWriteService.queue_page_setting_if_sql(
                        service,
                        "database",
                        "107",
                        setting_kind,
                        [],
                    )


class PageScaleProjectionTests(unittest.TestCase):
    def setUp(self):
        self.bid_ref = BidRef("test.mdb", "7")
        self.original = Page(uid="42", name="Page 42", scale_factor2=48.0)
        self.unrelated = Page(uid="43", name="Unrelated", scale_factor2=24.0)
        self.model = OstAggregate(Mock())
        self.model.current_bid_ref = self.bid_ref
        self.model.current_bid = Bid("7", "Test bid")
        self.model.set_pages({"42": self.original, "43": self.unrelated})
        self.data = ProjectDataService(self.model)
        self.persisted = {"42": replace(self.original), "43": replace(self.unrelated)}
        self.write_calls = []
        self.reloads = []
        self.events = EventBus()
        self.service = object.__new__(ProjectWriteService)
        self.service._project_data = self.data
        self.service._bid_write_guard = Mock()
        self.service._bid_write_guard.blocks_active_locked_bid_write.return_value = (
            False
        )
        self.service.uses_sql_collaboration_mutations = Mock(return_value=False)
        self.service.logger = logging.getLogger(__name__)
        self.service._event_bus = self.events
        self.service._reload_database = self._reload
        self.service._execute_database_mutation = (
            lambda _db, _resources, operation, **_kw: DatabaseMutationResult(
                operation_id=str(uuid.uuid4()),
                outcome_status=MutationOutcomeStatus.COMMITTED,
                value=operation(Mock()),
            )
        )
        self.writer = Mock()
        self.writer.save_page_scale.side_effect = self._write
        self.service._save_page_scale = SavePageScaleUseCase(self.writer)

    def _write(self, database, page_uid, sf1, sf2):
        self.write_calls.append((database, page_uid, sf1, sf2))
        self.persisted[page_uid] = replace(
            self.persisted[page_uid], scale_factor1=sf1, scale_factor2=sf2
        )
        return True

    def _reload(self, database):
        self.assertEqual(database, self.bid_ref.file_path)
        self.model.current_bid = Bid("7", "Test bid")
        self.model.set_pages(
            {uid: replace(page) for uid, page in self.persisted.items()}
        )
        self.reloads.append(self.model.get_page("42"))
        return True

    def test_scale_save_projects_only_affected_page_without_database_reload(self):
        changes = []
        self.events.subscribe(
            AppEvents.PAGE_METADATA_CHANGED,
            lambda **event: changes.append(event),
        )
        self.assertTrue(self.service.save_page_scale("test.mdb", "42", 1.0, 96.0))
        self.assertEqual(self.reloads, [])
        self.assertEqual(self.write_calls, [("test.mdb", "42", 1.0, 96.0)])
        self.assertEqual(self.persisted["42"].scale_factor2, 96.0)
        self.assertIs(self.data.get_page("42"), self.original)
        self.assertEqual(
            (self.original.scale_factor1, self.original.scale_factor2), (1.0, 96.0)
        )
        self.assertIs(self.data.get_page("43"), self.unrelated)
        self.assertEqual(self.unrelated.scale_factor2, 24.0)
        self.assertEqual(
            changes,
            [
                {
                    "database_id": "test.mdb",
                    "bid_uid": "7",
                    "page_uids": ("42",),
                    "changed_fields": ("scale",),
                }
            ],
        )

    def test_scale_save_does_not_project_into_bid_selected_during_write(self):
        replacement = Page(uid="42", name="Other bid page", scale_factor2=24.0)
        resources = []

        def execute(_database, requested, operation, **_options):
            resources.extend(requested)
            value = operation(Mock())
            self.model.current_bid_ref = BidRef("test.mdb", "8")
            self.model.current_bid = Bid("8", "Other bid")
            self.model.set_pages({"42": replacement})
            return DatabaseMutationResult(
                operation_id=str(uuid.uuid4()),
                outcome_status=MutationOutcomeStatus.COMMITTED,
                value=value,
            )

        reloads = []
        self.service._execute_database_mutation = execute
        self.service._reload_database = lambda path: reloads.append(path) or True
        self.assertTrue(self.service.save_page_scale("test.mdb", "42", 1.0, 96.0))
        self.assertEqual(str(resources[0].bid_uid), "7")
        self.assertEqual(replacement.scale_factor2, 24.0)
        self.assertEqual(reloads, ["test.mdb"])
        self.assertEqual(self.write_calls, [("test.mdb", "42", 1.0, 96.0)])
        self.assertEqual(self.persisted["42"].scale_factor2, 96.0)
        self.assertIs(self.data.get_page("42"), replacement)

    def test_failed_scale_write_preserves_model_and_does_not_reload_or_publish(self):
        self.writer.save_page_scale.side_effect = None
        self.writer.save_page_scale.return_value = False
        events = []
        self.events.subscribe(
            AppEvents.PAGE_METADATA_CHANGED, lambda **payload: events.append(payload)
        )
        self.events.subscribe(
            AppEvents.DATABASE_REFRESHED, lambda **payload: events.append(payload)
        )
        self.assertFalse(self.service.save_page_scale("test.mdb", "42", 1.0, 96.0))
        self.writer.save_page_scale.assert_called_once_with("test.mdb", "42", 1.0, 96.0)
        self.assertEqual(self.original.scale_factor2, 48.0)
        self.assertEqual(self.persisted["42"].scale_factor2, 48.0)
        self.assertEqual(self.reloads, [])
        self.assertEqual(events, [])

    def test_same_uid_page_replacement_during_scale_write_requires_reload(self):
        replacement = replace(self.original, scale_factor2=12.0)
        changes = []
        self.events.subscribe(
            AppEvents.PAGE_METADATA_CHANGED, lambda **payload: changes.append(payload)
        )

        def write(database, uid, sf1, sf2):
            self._write(database, uid, sf1, sf2)
            self.model.set_pages({"42": replacement})
            return True

        self.writer.save_page_scale.side_effect = write
        self.assertTrue(self.service.save_page_scale("test.mdb", "42", 1.0, 96.0))
        self.assertEqual(replacement.scale_factor2, 12.0)
        self.assertEqual(changes, [])
        self.assertEqual(len(self.reloads), 1)
        self.assertEqual(self.data.get_page("42").scale_factor2, 96.0)
        self.assertIsNot(self.data.get_page("42"), replacement)

    def test_bulk_scale_projects_only_saved_pages_and_reports_partial_failure(self):
        def write(database, uid, sf1, sf2):
            if uid == "43":
                return False
            return self._write(database, uid, sf1, sf2)

        self.writer.save_page_scale.side_effect = write
        changes = []
        self.events.subscribe(
            AppEvents.PAGE_METADATA_CHANGED, lambda **payload: changes.append(payload)
        )
        self.assertFalse(
            self.service.save_page_scales("test.mdb", ["42", "", "42", "43"], 1.0, 96.0)
        )
        self.assertEqual(
            [call.args for call in self.writer.save_page_scale.call_args_list],
            [("test.mdb", "42", 1.0, 96.0), ("test.mdb", "43", 1.0, 96.0)],
        )
        self.assertEqual(self.original.scale_factor2, 96.0)
        self.assertEqual(self.unrelated.scale_factor2, 24.0)
        self.assertEqual(self.reloads, [])
        self.assertEqual(
            changes,
            [
                {
                    "database_id": "test.mdb",
                    "bid_uid": "7",
                    "page_uids": ("42",),
                    "changed_fields": ("scale",),
                }
            ],
        )

    def test_empty_bulk_scale_is_a_noop_without_persistence_or_events(self):
        changes = []
        self.events.subscribe(
            AppEvents.PAGE_METADATA_CHANGED, lambda **payload: changes.append(payload)
        )
        self.assertFalse(self.service.save_page_scales("test.mdb", ["", ""], 1.0, 96.0))
        self.writer.save_page_scale.assert_not_called()
        self.assertEqual(self.reloads, [])
        self.assertEqual(changes, [])


class BidLockPermissionTests(unittest.TestCase):
    def test_takeoff_insert_exhaustion_returns_structured_failure(self):
        class UnavailableExecutor:
            def execute(self, _request, _operation):
                raise DatabaseConnectionUnavailableError(
                    "Restart OST Visualizer and try again."
                )

        project_data = _permissions__ProjectData()
        service, _, _, _ = _permissions__write_service(
            project_data,
            insert_takeoffs=_permissions__UseCase(["99"]),
            mutation_executor=UnavailableExecutor(),
        )
        result = service.insert_takeoffs_result(
            project_data.bid_ref.file_path,
            project_data.bid_ref.bid_uid,
            [
                InsertTakeoffSpec(
                    condition_uid="12",
                    page_uid="34",
                    area_uid="0",
                    position=[1.0, 2.0],
                )
            ],
            publish_database_refreshed_after_write=False,
        )
        self.assertFalse(result.success)
        self.assertFalse(result.write_success)
        self.assertFalse(result.reload_success)
        self.assertEqual(result.value, [])
        self.assertEqual(
            result.failure_reason,
            "Restart OST Visualizer and try again.",
        )

    def test_read_only_database_is_an_expected_deferred_write_block(self):
        capability = _permissions__DatabaseCapability(editable=False)
        service, *_unused = _permissions__write_service(
            _permissions__ProjectData(),
            database_capability=capability,
        )
        self.assertTrue(service.is_expected_deferred_write_blocked("sql-db"))
        capability.editable = True
        self.assertFalse(service.is_expected_deferred_write_blocked("sql-db"))

    def test_locked_bid_blocks_condition_edits_at_write_service(self):
        project_data = _permissions__ProjectData()
        project_data.locked = True
        service, _, _, _ = _permissions__write_service(project_data)
        result = service.update_condition(
            project_data.bid_ref.file_path,
            project_data.bid_ref.bid_uid,
            "12",
            UpdateConditionDto(),
        )
        self.assertFalse(result.success)
        self.assertEqual("The active bid is locked", result.error)

    def test_condition_update_preserves_typed_session_conflict_reason(self):
        project_data = _permissions__ProjectData()
        service, _, _, _ = _permissions__write_service(project_data)
        resource = ResourceRef("condition", "12", int(project_data.bid_ref.bid_uid))
        service._mutation_executor = SimpleNamespace(
            execute=lambda request, _operation: DatabaseMutationResult(
                operation_id=request.operation_id,
                outcome_status=MutationOutcomeStatus.CONFLICT,
                conflict=SynchronizationConflict(
                    database_id=project_data.bid_ref.file_path,
                    resource=resource,
                    reason="The SQL collaboration session expired.",
                    kind=SynchronizationConflictKind.SESSION,
                ),
            )
        )
        result = service.update_condition(
            project_data.bid_ref.file_path,
            project_data.bid_ref.bid_uid,
            "12",
            UpdateConditionDto(),
        )
        self.assertFalse(result.success)
        self.assertEqual("The SQL collaboration session expired.", result.error)

    def test_mdb_condition_update_publishes_targeted_fields_without_database_refresh(
        self,
    ):
        project_data = _permissions__ProjectData()
        events = _permissions__EventBus()
        service, _, _, _ = _permissions__write_service(project_data, event_bus=events)
        original = Condition(uid="12", name="Before", z_value=0.0)
        unrelated = Condition(uid="13", name="Unrelated")
        project_data.conditions = {"12": original, "13": unrelated}
        persisted = dict(project_data.conditions)

        def update(database, bid_uid, condition_uid, dto):
            self.assertEqual(
                (database, bid_uid, condition_uid),
                (project_data.bid_ref.file_path, "7", "12"),
            )
            self.assertEqual(events.published, [])
            persisted[condition_uid] = replace(
                persisted[condition_uid], **dto.get_changes()
            )
            return UpdateConditionResultDto(success=True)

        service._update_condition = SimpleNamespace(execute=update)
        service._condition_family_reader = Mock(
            side_effect=lambda *_args: (
                {uid: replace(condition) for uid, condition in persisted.items()},
                {},
            )
        )
        service._reload_database = Mock(
            side_effect=AssertionError("metadata edit must use the family reader")
        )
        updates = UpdateConditionDto()
        updates.set("name", "Level 2 (Top: 12'-0\")")
        updates.set("z_value", 144.0)
        result = service.update_condition(
            project_data.bid_ref.file_path,
            project_data.bid_ref.bid_uid,
            "12",
            updates,
        )
        self.assertTrue(result.success)
        self.assertIsNot(project_data.conditions["12"], original)
        self.assertEqual(project_data.conditions["12"].name, updates.get("name"))
        self.assertEqual(project_data.conditions["12"].z_value, 144.0)
        self.assertEqual(project_data.conditions["13"], unrelated)
        self.assertEqual(original.name, "Before")
        service._condition_family_reader.assert_called_once_with(
            project_data.bid_ref.file_path, "7"
        )
        service._reload_database.assert_not_called()
        self.assertEqual(
            events.published,
            [
                (
                    AppEvents.CONDITIONS_CHANGED,
                    {
                        "database_id": project_data.bid_ref.file_path,
                        "bid_uid": project_data.bid_ref.bid_uid,
                        "condition_uids": ["12"],
                        "changed_fields": ["name", "z_value"],
                        "change_operations": ["update"],
                        "invalidates_undo": False,
                        "local_completion": True,
                    },
                )
            ],
        )

    def test_condition_name_elevation_metadata_is_classified_for_mesh_refresh(self):
        project_data = _permissions__ProjectData()
        project_data.conditions["12"] = Condition(uid="12", name="Walls @T 10' - 0\"")
        events = _permissions__EventBus()
        service, _, _, _ = _permissions__write_service(project_data, event_bus=events)
        service._update_condition = _permissions__UseCase(
            UpdateConditionResultDto(success=True)
        )
        updates = UpdateConditionDto()
        updates.set("name", "Renamed Walls @B 8' - 0\"")
        result = service.update_condition(
            project_data.bid_ref.file_path,
            project_data.bid_ref.bid_uid,
            "12",
            updates,
        )
        self.assertTrue(result.success)
        self.assertEqual(len(events.published), 1)
        self.assertEqual(events.published[0][0], AppEvents.CONDITIONS_CHANGED)
        self.assertEqual(
            events.published[0][1]["changed_fields"],
            ["is_top", "name", "z_value"],
        )

    def test_plain_condition_rename_remains_non_mesh_metadata(self):
        project_data = _permissions__ProjectData()
        project_data.conditions["12"] = Condition(uid="12", name="Walls @T 10' - 0\"")
        events = _permissions__EventBus()
        service, _, _, _ = _permissions__write_service(project_data, event_bus=events)
        service._update_condition = _permissions__UseCase(
            UpdateConditionResultDto(success=True)
        )
        updates = UpdateConditionDto()
        updates.set("name", "Renamed Walls @T 10' - 0\"")
        result = service.update_condition(
            project_data.bid_ref.file_path,
            project_data.bid_ref.bid_uid,
            "12",
            updates,
        )
        self.assertTrue(result.success)
        self.assertEqual(len(events.published), 1)
        self.assertEqual(events.published[0][0], AppEvents.CONDITIONS_CHANGED)
        self.assertEqual(events.published[0][1]["changed_fields"], ["name"])

    def test_locked_bid_blocks_bid_internal_mutations_but_allows_status_change(self):
        project_data = _permissions__ProjectData()
        project_data.locked = True
        service, update_bid_job_status, _, _ = _permissions__write_service(project_data)
        self.assertEqual(
            [],
            service.insert_takeoffs(
                project_data.bid_ref.file_path,
                project_data.bid_ref.bid_uid,
                [
                    InsertTakeoffSpec(
                        condition_uid="12",
                        page_uid="34",
                        area_uid=None,
                        position=[1.0, 2.0],
                    )
                ],
            ),
        )
        self.assertFalse(
            service.save_cover_sheet(
                project_data.bid_ref.file_path,
                project_data.bid_ref.bid_uid,
                {"job_status_uid": 2},
            )
        )
        self.assertFalse(
            service.save_takeoffs_condition(
                project_data.bid_ref.file_path,
                ["12"],
                "34",
            )
        )
        self.assertTrue(
            service.update_bid_job_status(
                project_data.bid_ref.file_path,
                project_data.bid_ref.bid_uid,
                "2",
            )
        )
        self.assertEqual(
            update_bid_job_status.calls,
            [((project_data.bid_ref.file_path, "7", "2"), {})],
        )

    def test_write_service_rejects_incompatible_condition_reassignment_atomically(self):
        project_data = _permissions__ProjectData()
        project_data.conditions = {
            "linear": Condition(uid="linear", condition_type=Condition.TYPE_LINEAR),
            "area": Condition(uid="area", condition_type=Condition.TYPE_AREA),
        }
        linear_position = [0.0, 0.0, 10.0, 0.0]
        area_position = [0.0, 0.0, 10.0, 0.0, 10.0, 10.0, 0.0, 10.0]
        project_data.takeoffs = [
            Takeoff(
                uid="linear-takeoff",
                condition_uid="linear",
                position=list(linear_position),
            ),
            Takeoff(
                uid="area-takeoff",
                condition_uid="area",
                position=list(area_position),
            ),
        ]
        save_condition = _permissions__UseCase(True)
        service, *_ = _permissions__write_service(
            project_data,
            save_takeoffs_condition=save_condition,
        )
        rejected_requests = (
            (["linear-takeoff"], "area"),
            (["area-takeoff"], "linear"),
            (["linear-takeoff", "area-takeoff"], "linear"),
            (["missing"], "linear"),
        )
        with self.assertLogs(service.logger, level="WARNING") as captured:
            for takeoff_uids, target_uid in rejected_requests:
                with self.subTest(takeoff_uids=takeoff_uids, target_uid=target_uid):
                    self.assertFalse(
                        service.save_takeoffs_condition(
                            project_data.bid_ref.file_path,
                            takeoff_uids,
                            target_uid,
                            publish_database_refreshed_after_write=False,
                        )
                    )
            self.assertFalse(
                service.save_takeoffs_condition(
                    "C:/jobs/other.mdb",
                    ["linear-takeoff"],
                    "linear",
                    publish_database_refreshed_after_write=False,
                )
            )
        messages = "\n".join(captured.output)
        self.assertIn("Rejected incompatible", messages)
        self.assertIn("unknown takeoff", messages)
        self.assertIn("outside the active bid", messages)
        self.assertEqual(save_condition.calls, [])
        self.assertEqual(project_data.takeoffs[0].position, linear_position)
        self.assertEqual(project_data.takeoffs[1].position, area_position)
        self.assertEqual(project_data.takeoffs[0].condition_uid, "linear")
        self.assertEqual(project_data.takeoffs[1].condition_uid, "area")

    def test_write_service_allows_compatible_condition_reassignment(self):
        project_data = _permissions__ProjectData()
        project_data.conditions = {
            "linear-source": Condition(
                uid="linear-source", condition_type=Condition.TYPE_LINEAR
            ),
            "linear-target": Condition(
                uid="linear-target", condition_type=Condition.TYPE_LINEAR
            ),
        }
        project_data.takeoffs = [Takeoff(uid="takeoff", condition_uid="linear-source")]
        save_condition = _permissions__UseCase(True)
        service, *_ = _permissions__write_service(
            project_data,
            save_takeoffs_condition=save_condition,
        )
        result = service.save_takeoffs_condition(
            project_data.bid_ref.file_path,
            ["takeoff"],
            "linear-target",
            publish_database_refreshed_after_write=False,
        )
        self.assertTrue(result)
        self.assertEqual(
            save_condition.calls,
            [
                (
                    (
                        project_data.bid_ref.file_path,
                        ["takeoff"],
                        "linear-target",
                    ),
                    {},
                )
            ],
        )

    def test_locked_bid_allows_bid_delete_and_duplicate(self):
        project_data = _permissions__ProjectData()
        project_data.locked = True
        service, _, delete_bids, duplicate_bid = _permissions__write_service(
            project_data
        )
        self.assertTrue(
            service.delete_bids(
                project_data.bid_ref.file_path, [project_data.bid_ref.bid_uid]
            )
        )
        self.assertEqual(
            "new-bid",
            service.duplicate_bid(
                project_data.bid_ref.file_path, project_data.bid_ref.bid_uid
            ),
        )
        self.assertEqual(
            delete_bids.calls, [((project_data.bid_ref.file_path, ["7"]), {})]
        )
        self.assertEqual(
            duplicate_bid.calls, [((project_data.bid_ref.file_path, "7"), {})]
        )

    def test_write_service_reports_failure_when_required_reload_fails(self):
        project_data = _permissions__ProjectData()
        service, update_bid_job_status, delete_bids, duplicate_bid = (
            _permissions__write_service(project_data, reload_success=False)
        )
        self.assertFalse(
            service.delete_bids(
                project_data.bid_ref.file_path, [project_data.bid_ref.bid_uid]
            )
        )
        self.assertIsNone(
            service.duplicate_bid(
                project_data.bid_ref.file_path, project_data.bid_ref.bid_uid
            )
        )
        self.assertFalse(
            service.update_bid_job_status(
                project_data.bid_ref.file_path,
                project_data.bid_ref.bid_uid,
                "2",
            )
        )
        self.assertEqual(1, len(delete_bids.calls))
        self.assertEqual(1, len(duplicate_bid.calls))
        self.assertEqual(1, len(update_bid_job_status.calls))

    def test_create_project_result_distinguishes_refresh_failure_from_write_failure(
        self,
    ):
        project_data = _permissions__ProjectData()
        service, *_ = _permissions__write_service(project_data)
        create_project = _permissions__SequenceUseCase(
            ["project-new", "project-existing"]
        )
        service._create_project = create_project
        service._reload_database = lambda _file_path: False
        result = service.create_project_result(project_data.bid_ref.file_path, "New")
        self.assertFalse(result)
        self.assertTrue(result.write_success)
        self.assertTrue(result.refresh_failed)
        self.assertEqual(result.value, "project-new")
        self.assertIsNone(
            service.create_project(project_data.bid_ref.file_path, "Existing")
        )

    def test_duplicate_bid_result_keeps_created_uid_when_refresh_fails(self):
        project_data = _permissions__ProjectData()
        service, *_ = _permissions__write_service(project_data, reload_success=False)
        result = service.duplicate_bid_result(
            project_data.bid_ref.file_path, project_data.bid_ref.bid_uid
        )
        self.assertFalse(result)
        self.assertTrue(result.write_success)
        self.assertTrue(result.refresh_failed)
        self.assertEqual(result.value, "new-bid")

    def test_duplicate_bid_infrastructure_exception_is_not_converted_to_bool(self):
        project_data = _permissions__ProjectData()
        service, *_ = _permissions__write_service(project_data)
        expected_error = RuntimeError("duplicate infrastructure failure")

        class RaisingDuplicate:
            def execute(self, _file_path, _bid_uid):
                raise expected_error

        service._duplicate_bid = RaisingDuplicate()
        with self.assertRaises(RuntimeError) as captured:
            service.duplicate_bid_result(
                project_data.bid_ref.file_path,
                project_data.bid_ref.bid_uid,
                reload=False,
            )
        self.assertIs(captured.exception, expected_error)

    def test_condition_create_result_keeps_uid_when_refresh_fails(self):
        project_data = _permissions__ProjectData()
        service, *_ = _permissions__write_service(project_data, reload_success=False)
        service._insert_condition = _permissions__UseCase("condition-new")
        result = service.create_condition_result(
            project_data.bid_ref.file_path,
            project_data.bid_ref.bid_uid,
            CreateConditionSpec(name="Created"),
        )
        self.assertFalse(result)
        self.assertTrue(result.write_success)
        self.assertTrue(result.refresh_failed)
        self.assertEqual(result.value, "condition-new")

    def test_condition_duplicate_result_keeps_uids_when_refresh_fails(self):
        project_data = _permissions__ProjectData()
        service, *_ = _permissions__write_service(project_data, reload_success=False)
        service._duplicate_conditions = _permissions__UseCase(["condition-copy"])
        result = service.duplicate_conditions_result(
            project_data.bid_ref.file_path,
            project_data.bid_ref.bid_uid,
            ["condition-1"],
        )
        self.assertFalse(result)
        self.assertTrue(result.write_success)
        self.assertTrue(result.refresh_failed)
        self.assertEqual(result.value, ["condition-copy"])

    def test_layer_insert_result_keeps_uid_when_refresh_fails(self):
        project_data = _permissions__ProjectData()
        service, *_ = _permissions__write_service(project_data, reload_success=False)
        service._insert_layer = _permissions__UseCase("layer-new")
        result = service.insert_layer_result(
            project_data.bid_ref.file_path,
            project_data.bid_ref.bid_uid,
            "Layer",
            1,
        )
        self.assertFalse(result)
        self.assertTrue(result.write_success)
        self.assertTrue(result.refresh_failed)
        self.assertEqual(result.value, "layer-new")

    def test_condition_type_save_result_keeps_mapping_when_refresh_fails(self):
        project_data = _permissions__ProjectData()
        service, *_ = _permissions__write_service(project_data, reload_success=False)
        service._save_condition_types = _permissions__SequenceUseCase(
            [
                {"new_condition_type": "type-new"},
                {"new_condition_type": "type-existing"},
            ]
        )
        changes = {
            "new": [{"uid": "new_condition_type", "name": "Concrete"}],
            "updated": [],
            "deleted_uids": [],
        }
        result = service.save_condition_types_result(
            project_data.bid_ref.file_path, changes
        )
        self.assertFalse(result)
        self.assertTrue(result.write_success)
        self.assertTrue(result.refresh_failed)
        self.assertEqual(result.value, {"new_condition_type": "type-new"})
        self.assertIsNone(
            service.save_condition_types(project_data.bid_ref.file_path, changes)
        )

    def test_employee_save_result_keeps_mapping_when_refresh_fails(self):
        project_data = _permissions__ProjectData()
        service, *_ = _permissions__write_service(project_data, reload_success=False)
        service._save_employees = _permissions__SequenceUseCase(
            [{"new_0": "employee-new"}, {"new_0": "employee-copy"}]
        )
        changes = {
            "new": [Employee(uid="new_0")],
            "updated": [],
            "deleted_uids": [],
        }
        result = service.save_employees_result(project_data.bid_ref.file_path, changes)
        self.assertFalse(result)
        self.assertTrue(result.write_success)
        self.assertTrue(result.refresh_failed)
        self.assertEqual(result.value, {"new_0": "employee-new"})
        self.assertFalse(
            service.save_employees(project_data.bid_ref.file_path, changes)
        )
        self.assertEqual(len(service._save_employees.calls), 2)
        self.assertEqual(service._save_employees.results, [])

    def test_employee_save_result_can_skip_database_refresh(self):
        project_data = _permissions__ProjectData()
        service, *_ = _permissions__write_service(project_data)
        reload_calls = []
        service._reload_database = (
            lambda file_path: reload_calls.append(file_path) or True
        )
        service._save_employees = _permissions__UseCase({"new_0": "employee-new"})
        changes = {
            "new": [Employee(uid="new_0")],
            "updated": [],
            "deleted_uids": [],
        }
        result = service.save_employees_result(
            project_data.bid_ref.file_path,
            changes,
            publish_database_refreshed_after_write=False,
        )
        self.assertTrue(result)
        self.assertEqual(result.value, {"new_0": "employee-new"})
        self.assertEqual(reload_calls, [])

    def test_condition_type_save_result_reports_write_failure(self):
        project_data = _permissions__ProjectData()
        service, *_ = _permissions__write_service(project_data)
        service._save_condition_types = _permissions__SequenceUseCase([None])
        changes = {"new": [], "updated": [], "deleted_uids": ["type-used"]}
        result = service.save_condition_types_result(
            project_data.bid_ref.file_path, changes
        )
        self.assertFalse(result)
        self.assertFalse(result.write_success)
        self.assertFalse(result.reload_success)
        self.assertIsNone(result.value)

    def test_condition_type_save_result_can_skip_database_refresh(self):
        project_data = _permissions__ProjectData()
        service, *_ = _permissions__write_service(project_data)
        reload_calls = []
        service._reload_database = (
            lambda file_path: reload_calls.append(file_path) or True
        )
        service._save_condition_types = _permissions__UseCase(
            {"new_condition_type": "type-new"}
        )
        changes = {
            "new": [{"uid": "new_condition_type", "name": "Concrete"}],
            "updated": [],
            "deleted_uids": [],
        }
        result = service.save_condition_types_result(
            project_data.bid_ref.file_path,
            changes,
            publish_database_refreshed_after_write=False,
        )
        self.assertTrue(result)
        self.assertEqual(result.value, {"new_condition_type": "type-new"})
        self.assertEqual(reload_calls, [])

    def test_mdb_condition_type_save_publishes_catalog_change_without_database_event(
        self,
    ):
        project_data = _permissions__ProjectData()
        events = _permissions__EventBus()
        service, *_ = _permissions__write_service(project_data, event_bus=events)
        service._save_condition_types = _permissions__UseCase(
            {"new_condition_type": "type-new"}
        )
        changes = {
            "new": [{"uid": "new_condition_type", "name": "Concrete"}],
            "updated": [],
            "deleted_uids": [],
        }
        result = service.save_condition_types_result(
            project_data.bid_ref.file_path,
            changes,
        )
        self.assertTrue(result)
        self.assertEqual(
            events.published,
            [
                (
                    AppEvents.CONDITIONS_CHANGED,
                    {
                        "database_id": project_data.bid_ref.file_path,
                        "bid_uid": project_data.bid_ref.bid_uid,
                        "condition_uids": [],
                        "changed_fields": ["condition_type_catalog"],
                        "change_operations": [],
                        "invalidates_undo": False,
                        "local_completion": True,
                    },
                )
            ],
        )

    def test_condition_folder_delete_result_blocks_in_use_folder(self):
        project_data = _permissions__ProjectData()
        service, *_ = _permissions__write_service(project_data)
        service._project_data = SimpleNamespace(
            get_bid_condition_folders=lambda: {
                "folder-1": BidConditionFolder(uid="folder-1", name="Folder")
            },
            get_bid_conditions=lambda: {
                "cond-1": Condition(uid="cond-1", folder_uid="folder-1")
            },
        )
        delete_use_case = _permissions__UseCase(True)
        service._delete_condition_folders = delete_use_case
        result = service.delete_condition_folders_result(
            project_data.bid_ref.file_path,
            project_data.bid_ref.bid_uid,
            ["folder-1"],
        )
        self.assertFalse(result)
        self.assertFalse(result.write_success)
        self.assertEqual(result.failure_reason, "condition_folder_in_use")
        self.assertEqual(result.blocked_uids, ["folder-1"])
        self.assertEqual(delete_use_case.calls, [])

    def test_condition_folder_delete_result_allows_unused_folder(self):
        project_data = _permissions__ProjectData()
        service, *_ = _permissions__write_service(project_data)
        service._project_data = SimpleNamespace(
            get_bid_condition_folders=lambda: {
                "folder-1": BidConditionFolder(uid="folder-1", name="Folder")
            },
            get_bid_conditions=lambda: {},
            get_current_bid_ref=project_data.get_current_bid_ref,
            get_bid=project_data.get_bid,
            get_all_takeoffs=project_data.get_all_takeoffs,
            replace_condition_family=project_data.replace_condition_family,
        )
        delete_use_case = _permissions__UseCase(True)
        service._delete_condition_folders = delete_use_case
        result = service.delete_condition_folders_result(
            project_data.bid_ref.file_path,
            project_data.bid_ref.bid_uid,
            ["folder-1"],
        )
        self.assertTrue(result)
        self.assertEqual(result.value, ["folder-1"])
        self.assertEqual(
            delete_use_case.calls,
            [((project_data.bid_ref.file_path, ["folder-1"]), {})],
        )

    def test_condition_type_delete_result_blocks_in_use_type(self):
        project_data = _permissions__ProjectData()
        service, *_ = _permissions__write_service(project_data)
        service._condition_type_uids_in_use_provider = lambda _file_path: {"type-used"}
        save_use_case = _permissions__SequenceUseCase([{}])
        service._save_condition_types = save_use_case
        result = service.delete_condition_types_result(
            project_data.bid_ref.file_path, ["type-used"]
        )
        self.assertFalse(result)
        self.assertFalse(result.write_success)
        self.assertEqual(result.failure_reason, "condition_type_in_use")
        self.assertEqual(result.blocked_uids, ["type-used"])
        self.assertEqual(save_use_case.calls, [])

    def test_condition_type_delete_result_allows_unused_type(self):
        project_data = _permissions__ProjectData()
        service, *_ = _permissions__write_service(project_data)
        service._condition_type_uids_in_use_provider = lambda _file_path: {"type-used"}
        save_use_case = _permissions__SequenceUseCase([{}])
        service._save_condition_types = save_use_case
        result = service.delete_condition_types_result(
            project_data.bid_ref.file_path, ["type-unused"]
        )
        self.assertTrue(result)
        self.assertEqual(
            save_use_case.calls,
            [
                (
                    (
                        project_data.bid_ref.file_path,
                        {
                            "new": [],
                            "updated": [],
                            "deleted_uids": ["type-unused"],
                        },
                    ),
                    {},
                )
            ],
        )

    def test_condition_type_delete_fails_closed_when_usage_is_unavailable(self):
        project_data = _permissions__ProjectData()
        for provider in (
            None,
            lambda _file_path: (_ for _ in ()).throw(RuntimeError("read failed")),
        ):
            with self.subTest(provider=provider):
                service, *_ = _permissions__write_service(project_data)
                service._condition_type_uids_in_use_provider = provider
                save_use_case = _permissions__SequenceUseCase([{}])
                service._save_condition_types = save_use_case
                result = service.delete_condition_types_result(
                    project_data.bid_ref.file_path, ["type-unknown"]
                )
                self.assertFalse(result)
                self.assertFalse(result.write_success)
                self.assertEqual(
                    result.failure_reason, "condition_type_usage_unavailable"
                )
                self.assertEqual(result.blocked_uids, ["type-unknown"])
                self.assertEqual(save_use_case.calls, [])

    def test_delete_pages_normalizes_empty_and_duplicate_uids(self):
        project_data = _permissions__ProjectData()
        service, *_ = _permissions__write_service(project_data)
        delete_use_case = _permissions__UseCase(True)
        service._delete_pages = delete_use_case
        self.assertTrue(
            service.delete_pages(
                project_data.bid_ref.file_path,
                ["page-1", "", "page-1", "page-2"],
            )
        )
        self.assertEqual(
            delete_use_case.calls,
            [
                (
                    (
                        project_data.bid_ref.file_path,
                        ["page-1", "page-2"],
                    ),
                    {},
                )
            ],
        )

    def test_batch_layer_delete_reports_partial_success_and_reloads_once(self):
        project_data = _permissions__ProjectData()
        service, *_ = _permissions__write_service(project_data)
        delete_layer = _permissions__SequenceUseCase([True, False])
        reload_calls = []
        service._delete_layer = delete_layer
        service._reload_database = (
            lambda file_path: reload_calls.append(file_path) or True
        )
        result = service.delete_layers(
            project_data.bid_ref.file_path, ["layer-1", "layer-2"]
        )
        self.assertFalse(result)
        self.assertTrue(result.any_success)
        self.assertTrue(result.partial_success)
        self.assertEqual(result.succeeded_uids, ["layer-1"])
        self.assertEqual(result.failed_uids, ["layer-2"])
        self.assertEqual(len(delete_layer.calls), 2)
        self.assertEqual(reload_calls, [project_data.bid_ref.file_path])

    def test_save_bid_areas_requires_uid_map_for_new_area(self):
        project_data = _permissions__ProjectData()
        service, *_ = _permissions__write_service(project_data)
        service._save_bid_areas = _permissions__UseCase({})
        changes = BidAreaChangeset(
            new=[
                BidArea(
                    uid="new_0",
                    bid_uid=project_data.bid_ref.bid_uid,
                    parent_uid="",
                    name="Area 2",
                    sequence=0,
                )
            ],
            updated=[],
            deleted_uids=[],
        )
        self.assertIsNone(
            service.save_bid_areas(
                project_data.bid_ref.file_path,
                project_data.bid_ref.bid_uid,
                changes,
            )
        )

    def test_save_bid_areas_reports_reload_failure_for_existing_changes(self):
        project_data = _permissions__ProjectData()
        service, *_ = _permissions__write_service(project_data, reload_success=False)
        service._save_bid_areas = _permissions__UseCase({})
        changes = BidAreaChangeset(
            new=[],
            updated=[
                BidArea(
                    uid="area-1",
                    bid_uid=project_data.bid_ref.bid_uid,
                    parent_uid="",
                    name="Area 1",
                    sequence=0,
                )
            ],
            deleted_uids=[],
        )
        self.assertIsNone(
            service.save_bid_areas(
                project_data.bid_ref.file_path,
                project_data.bid_ref.bid_uid,
                changes,
            )
        )

    def test_save_bid_areas_result_preserves_uid_map_when_refresh_fails(self):
        project_data = _permissions__ProjectData()
        service, *_ = _permissions__write_service(project_data, reload_success=False)
        service._save_bid_areas = _permissions__UseCase({"new_0": "area-2"})
        changes = BidAreaChangeset(
            new=[
                BidArea(
                    uid="new_0",
                    bid_uid=project_data.bid_ref.bid_uid,
                    parent_uid="",
                    name="Area 2",
                    sequence=0,
                )
            ],
            updated=[],
            deleted_uids=[],
        )
        result = service.save_bid_areas_result(
            project_data.bid_ref.file_path,
            project_data.bid_ref.bid_uid,
            changes,
        )
        self.assertTrue(result.write_success)
        self.assertTrue(result.refresh_failed)
        self.assertEqual(result.value, {"new_0": "area-2"})
        self.assertIsNone(
            service.save_bid_areas(
                project_data.bid_ref.file_path,
                project_data.bid_ref.bid_uid,
                changes,
            )
        )

    def test_save_bid_areas_result_can_skip_database_refresh(self):
        project_data = _permissions__ProjectData()
        service, *_ = _permissions__write_service(project_data)
        reload_calls = []
        service._reload_database = (
            lambda file_path: reload_calls.append(file_path) or True
        )
        service._save_bid_areas = _permissions__UseCase({"new_0": "area-2"})
        changes = BidAreaChangeset(
            new=[
                BidArea(
                    uid="new_0",
                    bid_uid=project_data.bid_ref.bid_uid,
                    parent_uid="",
                    name="Area 2",
                    sequence=0,
                )
            ],
            updated=[],
            deleted_uids=[],
        )
        result = service.save_bid_areas_result(
            project_data.bid_ref.file_path,
            project_data.bid_ref.bid_uid,
            changes,
            publish_database_refreshed_after_write=False,
        )
        self.assertTrue(result)
        self.assertEqual(result.value, {"new_0": "area-2"})
        self.assertEqual(reload_calls, [])


class TakeoffLifecycleRequestTests(unittest.TestCase):
    def test_nested_parent_paste_remaps_each_generation_on_both_backends(self):
        payload = MdbSqlBehaviorParityTests._mixed_paste_payload()
        payload = replace(
            payload,
            takeoff_source_uids=("grandchild", "hole", "parent"),
            takeoff_specs=(
                replace(payload.takeoff_specs[1], parent_uid="hole"),
                payload.takeoff_specs[1],
                payload.takeoff_specs[0],
            ),
            annotation_source_uids=(),
            annotation_specs=(),
        )
        for sql in (False, True):
            with self.subTest(sql=sql):
                if sql:
                    service, provider = (
                        MdbSqlBehaviorParityTests._queued_project_service()
                    )
                else:
                    service = MdbSqlBehaviorParityTests._local_composite_service()
                service._insert_takeoffs = _SequenceUseCase(
                    ["p-new"], ["h-new"], ["g-new"]
                )
                if sql:
                    service.queue_plan_items_paste("database", payload, lambda _r: None)
                    result = provider.requests[-1][1]()
                else:
                    result = service.execute_plan_items_paste_local("database", payload)
                self.assertEqual(result.outcome_status, MutationOutcomeStatus.COMMITTED)
                self.assertEqual(
                    [call[2][0].parent_uid for call in service._insert_takeoffs.calls],
                    ["0", "p-new", "h-new"],
                )

    def test_queued_placement_retains_submission_snapshot_and_dependencies(self):
        queued = []
        written = []
        service = ProjectWriteService.__new__(ProjectWriteService)
        service._sql_collaboration_provider = lambda: SimpleNamespace(
            queue_request=lambda *args, **kwargs: queued.append(args) or 1
        )

        def insert(_database, _bid, specs, **kwargs):
            written.extend(deepcopy(specs))
            return DatabaseMutationResult(
                operation_id=kwargs["operation_id"],
                outcome_status=MutationOutcomeStatus.COMMITTED,
                value=["101"],
            )

        service._insert_takeoffs_mutation = insert
        spec = InsertTakeoffSpec(
            condition_uid="10",
            page_uid="20",
            area_uid="30",
            parent_uid="40",
            position=[1.25, 2.75],
            raw_extras={"FontName": "Original"},
        )
        specs = [spec]
        expected = deepcopy(spec)
        service.queue_takeoff_placement(
            "database",
            "8",
            specs,
            "7b3c5ac1-e623-44aa-8203-26a0125873b9",
            lambda _result: None,
        )
        spec.position[0] = 99
        spec.page_uid = "21"
        spec.parent_uid = "41"
        spec.raw_extras["FontName"] = "Changed"
        specs.append(deepcopy(spec))
        result = queued[0][1]()
        self.assertEqual(written, [expected])
        self.assertEqual(result.authoritative_result.affected_page_uids, ("20",))
        self.assertEqual(queued[0][0].payload, (expected,))


class MdbSqlBehaviorParityTests(unittest.TestCase):
    @staticmethod
    def _local_composite_service():
        service = ProjectWriteService.__new__(ProjectWriteService)
        service.uses_sql_collaboration_mutations = lambda _database_id: False
        # A real guard over an unlocked Bid: the composite Access commands consult it
        # (decision D8), so a bare __new__ service needs one.
        service._bid_write_guard = ActiveBidWriteGuard(
            SimpleNamespace(is_current_bid_locked=lambda: False)
        )
        service.reload_calls = []
        service.reload_and_notify = (
            lambda database_id: service.reload_calls.append(database_id) or True
        )
        service.mutation_calls = []

        def execute_mutation(database_id, resources, operation, **options):
            service.mutation_calls.append((database_id, resources, options))
            value = operation(_Recorder())
            return DatabaseMutationResult(
                operation_id=str(uuid.uuid4()),
                outcome_status=MutationOutcomeStatus.COMMITTED,
                value=value,
            )

        service._execute_database_mutation = execute_mutation
        service._duplicate_conditions = _SequenceUseCase({})
        service._insert_takeoffs = _SequenceUseCase(["parent-new"], ["hole-new"])
        service._insert_annotations = _SequenceUseCase(["named-new"], ["rect-new"])
        service._delete_takeoffs = _SequenceUseCase(True)
        service._delete_annotations = _SequenceUseCase(True)
        service._save_takeoff_positions = _SequenceUseCase(True)
        service._save_takeoff_rotations = _SequenceUseCase(True)
        service._save_annotation_positions = _SequenceUseCase(True)
        service._save_takeoff_text_properties = _SequenceUseCase(True)
        service._save_takeoffs_area = _SequenceUseCase(True)
        service._save_takeoffs_condition = _SequenceUseCase(True)
        service._set_takeoffs_negative = _SequenceUseCase(True)
        service._set_takeoff_curve = _SequenceUseCase(True)
        service._save_annotation_text_properties = _SequenceUseCase(True)
        service._save_annotation_styles = _SequenceUseCase(True)
        service._mutation_executor = SimpleNamespace(
            verify_plan_items_exist=lambda *_args, **_kwargs: None
        )
        return service

    @staticmethod
    def _mixed_paste_payload():
        return PlanItemsPastePayload(
            source_bid_uid="7",
            destination_bid_uid="7",
            takeoff_source_uids=("parent", "hole"),
            takeoff_specs=(
                InsertTakeoffSpec(
                    condition_uid="c1",
                    page_uid="p1",
                    area_uid="0",
                    position=[0.0, 0.0, 10.0, 0.0],
                    parent_uid="0",
                ),
                InsertTakeoffSpec(
                    condition_uid="c1",
                    page_uid="p1",
                    area_uid="0",
                    position=[2.0, 2.0, 4.0, 2.0],
                    parent_uid="parent",
                    is_negative=True,
                ),
            ),
            annotation_source_uids=(
                annotation_resource_id("namedview", "shared"),
                annotation_resource_id("rect", "shared"),
            ),
            annotation_specs=(
                InsertAnnotationSpec(
                    page_uid="p1",
                    annotation_type="namedview",
                    position=[0.0, 0.0, 1.0, 1.0],
                    color="#000000",
                    width=1.0,
                ),
                InsertAnnotationSpec(
                    page_uid="p1",
                    annotation_type="rect",
                    position=[1.0, 1.0, 2.0, 2.0],
                    color="#000000",
                    width=1.0,
                ),
            ),
        )

    def test_mdb_mixed_paste_runs_as_one_application_mutation(self):
        service = self._local_composite_service()
        result = service.execute_plan_items_paste_local(
            "database.mdb",
            self._mixed_paste_payload(),
            publish_database_refreshed_after_write=False,
        )
        self.assertEqual(result.outcome_status, MutationOutcomeStatus.COMMITTED)
        self.assertEqual(len(service.mutation_calls), 1)
        maps = dict(result.authoritative_result.created_uid_maps)
        self.assertEqual(
            dict(maps["takeoffs"]),
            {"hole": "hole-new", "parent": "parent-new"},
        )
        self.assertEqual(
            dict(maps["annotations"]),
            {
                annotation_resource_id("namedview", "shared"): "named-new",
                annotation_resource_id("rect", "shared"): "rect-new",
            },
        )
        self.assertEqual(service.reload_calls, [])

    def test_sql_mixed_paste_distinguishes_table_scoped_annotation_uids(self):
        service, provider = self._queued_project_service()
        service._insert_takeoffs = _SequenceUseCase(["parent-new"], ["hole-new"])
        service._insert_annotations = _SequenceUseCase(["named-new"], ["rect-new"])
        generation = service.queue_plan_items_paste(
            "database",
            self._mixed_paste_payload(),
            lambda _result: None,
        )
        result = provider.requests[0][1]()
        self.assertEqual(generation, 41)
        self.assertEqual(result.outcome_status, MutationOutcomeStatus.COMMITTED)
        maps = dict(result.authoritative_result.created_uid_maps)
        self.assertEqual(
            dict(maps["annotations"]),
            {
                annotation_resource_id("namedview", "shared"): "named-new",
                annotation_resource_id("rect", "shared"): "rect-new",
            },
        )
        self.assertEqual(
            service._insert_annotations.calls[1][3].namedview_uids,
            {"shared": "named-new"},
        )

    def test_mdb_and_sql_restore_backouts_after_authoritative_parent_allocation(self):
        parent, hole = self._mixed_paste_payload().takeoff_specs
        payload = PlanItemsPastePayload(
            source_bid_uid="7",
            destination_bid_uid="7",
            # Children may precede their parents in the selection snapshot.
            takeoff_source_uids=("hole-b", "parent-a", "hole-a", "parent-b"),
            takeoff_specs=(
                replace(hole, parent_uid="parent-b"),
                parent,
                replace(hole, parent_uid="parent-a"),
                parent,
            ),
        )
        for sql in (False, True):
            for cycle in range(2):
                with self.subTest(sql=sql, cycle=cycle):
                    if sql:
                        service, provider = self._queued_project_service()
                    else:
                        service = self._local_composite_service()
                    parents = [f"a-{cycle}", f"b-{cycle}"]
                    holes = [f"hole-b-{cycle}", f"hole-a-{cycle}"]
                    service._insert_takeoffs = _SequenceUseCase(parents, holes)
                    if sql:
                        service.queue_plan_items_paste(
                            "database", payload, lambda _r: None
                        )
                        result = provider.requests[0][1]()
                    else:
                        result = service.execute_plan_items_paste_local(
                            "database.mdb", payload
                        )
                    self.assertEqual(
                        result.outcome_status, MutationOutcomeStatus.COMMITTED
                    )
                    calls = service._insert_takeoffs.calls
                    self.assertEqual(
                        [spec.parent_uid for spec in calls[0][2]], ["0", "0"]
                    )
                    self.assertEqual(
                        [spec.parent_uid for spec in calls[1][2]], parents[::-1]
                    )
                    self.assertEqual(
                        [spec.position for spec in calls[1][2]], [hole.position] * 2
                    )
                    uid_map = dict(
                        dict(result.authoritative_result.created_uid_maps)["takeoffs"]
                    )
                    self.assertEqual(
                        uid_map,
                        dict(
                            zip(
                                ("parent-a", "parent-b", "hole-b", "hole-a"),
                                parents + holes,
                            )
                        ),
                    )

    def test_mdb_and_sql_restore_backout_with_existing_external_parent(self):
        parent, hole = self._mixed_paste_payload().takeoff_specs
        payload = PlanItemsPastePayload(
            source_bid_uid="7",
            destination_bid_uid="7",
            takeoff_source_uids=("child",),
            takeoff_specs=(replace(hole, parent_uid="retained-parent"),),
        )
        for sql in (False, True):
            with self.subTest(sql=sql):
                if sql:
                    service, provider = self._queued_project_service()
                    service._insert_takeoffs = _SequenceUseCase(["restored-child"])
                    service.queue_plan_items_paste("database", payload, lambda _r: None)
                    result = provider.requests[0][1]()
                    self.assertIn(
                        ResourceRef("takeoff", "retained-parent", 7),
                        provider.requests[0][0].dependency_resources,
                    )
                else:
                    service = self._local_composite_service()
                    result = service.execute_plan_items_paste_local(
                        "database.mdb", payload
                    )
                self.assertEqual(result.outcome_status, MutationOutcomeStatus.COMMITTED)
                calls = service._insert_takeoffs.calls
                self.assertEqual(len(calls), 1)
                self.assertEqual(calls[0][2][0].parent_uid, "retained-parent")
                self.assertEqual(calls[0][2][0].position, hole.position)

    def test_sql_plan_paste_locks_takeoff_area_dependency(self):
        service, provider = self._queued_project_service()
        service._insert_takeoffs = _SequenceUseCase(["takeoff-new"])
        payload = PlanItemsPastePayload(
            source_bid_uid="7",
            destination_bid_uid="7",
            takeoff_source_uids=("takeoff-1",),
            takeoff_specs=(
                InsertTakeoffSpec(
                    condition_uid="condition-1",
                    page_uid="page-1",
                    area_uid="area-1",
                    position=[0.0, 0.0],
                ),
            ),
            annotation_source_uids=(),
            annotation_specs=(),
        )
        service.queue_plan_items_paste("database", payload, lambda _result: None)
        request, _execute, _callback = provider.requests[0]
        self.assertIn(ResourceRef("area", "area-1", 7), request.dependency_resources)
        self.assertEqual(service._insert_takeoffs.calls, [])
        result = _execute()
        self.assertEqual(result.outcome_status, MutationOutcomeStatus.COMMITTED)
        self.assertEqual(
            service._insert_takeoffs.calls,
            [("database", "7", list(payload.takeoff_specs))],
        )
        self.assertEqual(result.authoritative_result.affected_page_uids, ("page-1",))

    def test_sql_plan_paste_locks_existing_hot_link_named_view_dependency(self):
        service, provider = self._queued_project_service()
        service._insert_annotations = _SequenceUseCase(["hotlink-new"])
        payload = PlanItemsPastePayload(
            source_bid_uid="7",
            destination_bid_uid="7",
            annotation_source_uids=(annotation_resource_id("hotlink", "12"),),
            annotation_specs=(
                InsertAnnotationSpec(
                    page_uid="page-1",
                    annotation_type="hotlink",
                    position=[0.0, 0.0],
                    color="#000000",
                    width=1.0,
                    properties={"BidPageViewUID": "55"},
                ),
            ),
        )
        service.queue_plan_items_paste("database", payload, lambda _result: None)
        request, _execute, _callback = provider.requests[0]
        self.assertIn(
            ResourceRef("annotation", annotation_resource_id("namedview", "55"), 7),
            request.dependency_resources,
        )
        self.assertEqual(service._insert_annotations.calls, [])
        result = _execute()
        self.assertEqual(result.outcome_status, MutationOutcomeStatus.COMMITTED)
        self.assertEqual(len(service._insert_annotations.calls), 1)
        self.assertEqual(
            service._insert_annotations.calls[0][:3],
            ("database", "7", list(payload.annotation_specs)),
        )
        self.assertEqual(result.authoritative_result.affected_page_uids, ("page-1",))

    def test_cross_bid_plan_paste_clears_external_hot_link_target(self):
        service, provider = self._queued_project_service()
        service._insert_annotations = _SequenceUseCase(["hotlink-new"])
        payload = PlanItemsPastePayload(
            source_bid_uid="6",
            destination_bid_uid="7",
            annotation_source_uids=(annotation_resource_id("hotlink", "12"),),
            annotation_specs=(
                InsertAnnotationSpec(
                    page_uid="page-1",
                    annotation_type="hotlink",
                    position=[0.0, 0.0],
                    color="#000000",
                    width=1.0,
                    properties={"BidPageViewUID": "55"},
                ),
            ),
        )
        service.queue_plan_items_paste("database", payload, lambda _result: None)
        request, execute, _callback = provider.requests[0]
        result = execute()
        self.assertEqual(result.outcome_status, MutationOutcomeStatus.COMMITTED)
        inserted_spec = service._insert_annotations.calls[0][2][0]
        self.assertIsNone(inserted_spec.properties["BidPageViewUID"])
        self.assertNotIn(
            ResourceRef("annotation", annotation_resource_id("namedview", "55"), 7),
            request.dependency_resources,
        )

    def test_plan_paste_does_not_lock_named_view_created_in_same_payload(self):
        service, provider = self._queued_project_service()
        service._insert_annotations = _SequenceUseCase(
            ["named-view-new"], ["hot-link-new"]
        )
        payload = PlanItemsPastePayload(
            source_bid_uid="7",
            destination_bid_uid="7",
            annotation_source_uids=(
                annotation_resource_id("namedview", "55"),
                annotation_resource_id("hotlink", "12"),
            ),
            annotation_specs=(
                InsertAnnotationSpec(
                    page_uid="page-1",
                    annotation_type="namedview",
                    position=[0.0, 0.0, 1.0, 1.0],
                    color="#000000",
                    width=1.0,
                ),
                InsertAnnotationSpec(
                    page_uid="page-1",
                    annotation_type="hotlink",
                    position=[0.0, 0.0],
                    color="#000000",
                    width=1.0,
                    properties={"BidPageViewUID": "55"},
                ),
            ),
        )
        service.queue_plan_items_paste("database", payload, lambda _result: None)
        request, execute, _callback = provider.requests[0]
        self.assertNotIn(
            ResourceRef("annotation", annotation_resource_id("namedview", "55"), 7),
            request.dependency_resources,
        )
        result = execute()
        self.assertEqual(result.outcome_status, MutationOutcomeStatus.COMMITTED)
        self.assertEqual(
            service._insert_annotations.calls[1][3].namedview_uids,
            {"55": "named-view-new"},
        )

    def test_mdb_mixed_paste_failure_has_no_success_projection(self):
        stage_overrides = {
            "parents": ("_insert_takeoffs", _SequenceUseCase([])),
            "holes": (
                "_insert_takeoffs",
                _SequenceUseCase(["parent-new"], []),
            ),
            "named_views": ("_insert_annotations", _SequenceUseCase([])),
            "annotations": (
                "_insert_annotations",
                _SequenceUseCase(
                    ["named-new"],
                    RuntimeError("forced annotation failure"),
                ),
            ),
        }
        for stage, (attribute, use_case) in stage_overrides.items():
            with self.subTest(stage=stage):
                service = self._local_composite_service()
                setattr(service, attribute, use_case)
                result = service.execute_plan_items_paste_local(
                    "database.mdb",
                    self._mixed_paste_payload(),
                )
                self.assertEqual(
                    result.outcome_status,
                    MutationOutcomeStatus.FAILED_BEFORE_COMMIT,
                )
                self.assertEqual(len(service.mutation_calls), 1)
                self.assertIsNone(result.authoritative_result)
                self.assertEqual(service.reload_calls, [])

    def test_mdb_mixed_delete_runs_as_one_application_mutation(self):
        service = self._local_composite_service()
        result = service.execute_plan_items_delete_local(
            "database.mdb",
            "7",
            ["takeoff-1"],
            [("annotation-1", "rect")],
            page_uids=("p1",),
            publish_database_refreshed_after_write=False,
        )
        self.assertEqual(result.outcome_status, MutationOutcomeStatus.COMMITTED)
        self.assertEqual(len(service.mutation_calls), 1)
        self.assertEqual(len(service._delete_takeoffs.calls), 1)
        self.assertEqual(len(service._delete_annotations.calls), 1)
        self.assertEqual(service.reload_calls, [])

    def test_mdb_mixed_delete_removes_endpoint_annotation_before_takeoff_cascade(self):
        service = self._local_composite_service()
        endpoint_line_exists = [True]
        call_order = []

        class DeleteEndpointLine:
            def execute(self, _database_id, annotations):
                call_order.append(("annotations", list(annotations)))
                if not endpoint_line_exists[0]:
                    return False
                endpoint_line_exists[0] = False
                return True

        class DeleteTakeoffAndCompanions:
            def execute(self, _database_id, takeoff_uids):
                call_order.append(("takeoffs", list(takeoff_uids)))
                endpoint_line_exists[0] = False
                return True

        service._delete_annotations = DeleteEndpointLine()
        service._delete_takeoffs = DeleteTakeoffAndCompanions()
        result = service.execute_plan_items_delete_local(
            "database.mdb",
            "7",
            ["takeoff-1"],
            [("line-1", "line")],
            publish_database_refreshed_after_write=False,
        )
        self.assertEqual(result.outcome_status, MutationOutcomeStatus.COMMITTED)
        self.assertEqual(
            call_order,
            [
                ("annotations", [("line-1", "line")]),
                ("takeoffs", ["takeoff-1"]),
            ],
        )

    def test_mdb_mixed_delete_failure_has_no_success_projection(self):
        for stage, attribute in (
            ("takeoffs", "_delete_takeoffs"),
            ("annotations", "_delete_annotations"),
        ):
            with self.subTest(stage=stage):
                service = self._local_composite_service()
                setattr(service, attribute, _SequenceUseCase(False))
                result = service.execute_plan_items_delete_local(
                    "database.mdb",
                    "7",
                    ["takeoff-1"],
                    [("annotation-1", "rect")],
                )
                self.assertEqual(
                    result.outcome_status,
                    MutationOutcomeStatus.FAILED_BEFORE_COMMIT,
                )
                self.assertEqual(len(service.mutation_calls), 1)
                self.assertIsNone(result.authoritative_result)
                self.assertEqual(service.reload_calls, [])

    def test_mdb_mixed_geometry_runs_in_one_application_mutation(self):
        service = self._local_composite_service()
        result = service.execute_plan_geometry_local(
            "database.mdb",
            "7",
            takeoff_positions=[("10", [1.0, 2.0])],
            annotation_positions=[("10", "line", [3.0, 4.0])],
            page_uids=("p1",),
            publish_database_refreshed_after_write=False,
        )
        self.assertEqual(result.outcome_status, MutationOutcomeStatus.COMMITTED)
        self.assertEqual(len(service.mutation_calls), 1)
        self.assertEqual(
            set(result.authoritative_result.updated_resources),
            {
                ResourceRef("takeoff", "10", 7),
                ResourceRef("annotation", "line/10", 7),
            },
        )

    def test_mdb_mixed_geometry_late_failure_has_no_success_projection(self):
        service = self._local_composite_service()
        service._save_annotation_positions = _SequenceUseCase(False)
        result = service.execute_plan_geometry_local(
            "database.mdb",
            "7",
            takeoff_positions=[("10", [1.0, 2.0])],
            annotation_positions=[("10", "line", [3.0, 4.0])],
            publish_database_refreshed_after_write=False,
        )
        self.assertEqual(
            result.outcome_status,
            MutationOutcomeStatus.FAILED_BEFORE_COMMIT,
        )
        self.assertIsNone(result.authoritative_result)
        self.assertEqual(service.reload_calls, [])

    def test_local_property_replay_restores_distinct_original_areas_atomically(self):
        service = self._local_composite_service()
        service._save_takeoffs_area = _SequenceUseCase(True, True)
        service._project_data = SimpleNamespace(
            get_current_bid_ref=lambda: BidRef("database.mdb", "7"),
            get_all_takeoffs=lambda: [
                Takeoff(uid=uid, page_uid="20", condition_uid="30")
                for uid in ("takeoff-1", "takeoff-2")
            ],
        )
        result = service.execute_plan_properties_local(
            "database.mdb",
            "7",
            "takeoff_area",
            [("takeoff-1", "area-1"), ("takeoff-2", "area-2")],
            publish_database_refreshed_after_write=False,
        )
        self.assertEqual(result.outcome_status, MutationOutcomeStatus.COMMITTED)
        self.assertEqual(len(service.mutation_calls), 1)
        self.assertEqual(
            service._save_takeoffs_area.calls,
            [
                ("database.mdb", ["takeoff-1"], "area-1"),
                ("database.mdb", ["takeoff-2"], "area-2"),
            ],
        )

    @staticmethod
    def _queued_project_service():
        service = ProjectWriteService.__new__(ProjectWriteService)
        provider = _CapturedQueueProvider()
        service._sql_collaboration_provider = lambda: provider
        # Decision F2: the queued condition-folder commands consult the guard, so this
        # bare service needs a real one over an unlocked Bid.
        service._bid_write_guard = ActiveBidWriteGuard(
            SimpleNamespace(is_current_bid_locked=lambda: False)
        )
        service._project_data = SimpleNamespace(
            get_page_takeoffs=lambda _page_uid: [SimpleNamespace(uid="takeoff-1")],
            get_page_annotations=lambda _page_uid: [
                SimpleNamespace(uid="annotation-1", annotation_type="rect")
            ],
            get_project_bid_uids=lambda _database_id, _project_uids: [],
            get_bid_conditions=lambda: {},
        )
        service._create_project = _SequenceUseCase("project-new")
        service._create_bid = _SequenceUseCase("8")
        service._rename_project = _SequenceUseCase(True)
        service._move_bids = _SequenceUseCase(True)
        service._duplicate_bid = _SequenceUseCase("8")
        service._delete_bids = _SequenceUseCase(True)
        service._delete_projects = _SequenceUseCase(True)
        service._update_bid_job_status = _SequenceUseCase(True)
        service._delete_pages = _SequenceUseCase(True)
        service._insert_layer = _SequenceUseCase("layer-new")
        service._delete_layer = _SequenceUseCase(True)
        service._swap_layer_sequence = _SequenceUseCase(True)
        service._update_layer_name = _SequenceUseCase(True)
        service._update_layer_show = _SequenceUseCase(True)
        service._update_all_layers_show = _SequenceUseCase(True)
        service._insert_condition = _SequenceUseCase("condition-new")
        service._delete_conditions = _SequenceUseCase(True)
        service._duplicate_conditions = _SequenceUseCase(["condition-copy"])
        service._update_condition = _SequenceUseCase(
            UpdateConditionResultDto(success=True)
        )
        service._renumber_conditions = _SequenceUseCase(True)
        service._insert_condition_folder = _SequenceUseCase("folder-new")
        service._rename_condition_folder = _SequenceUseCase(True)
        service._delete_condition_folders = _SequenceUseCase(True)
        service._save_condition_types = _SequenceUseCase(
            {"new_condition_type": "type-new"}
        )
        service._save_cover_sheet = _SequenceUseCase(True)
        service._save_page_name = _SequenceUseCase(True)
        service._save_job_statuses = _SequenceUseCase({"new_status": "status-new"})
        service._save_employees = _SequenceUseCase({"new_employee": "employee-new"})
        service._save_pay_classes = _SequenceUseCase({"new_pay_class": "pay-class-new"})
        service._delete_takeoffs = _SequenceUseCase(True)
        service._delete_annotations = _SequenceUseCase(True)
        service._save_takeoff_positions = _SequenceUseCase(True)
        service._save_takeoff_rotations = _SequenceUseCase(True)
        service._save_annotation_positions = _SequenceUseCase(True)
        service._save_takeoff_text_properties = _SequenceUseCase(True)
        service._save_takeoffs_area = _SequenceUseCase(True)
        service._save_takeoffs_condition = _SequenceUseCase(True)
        service._set_takeoffs_negative = _SequenceUseCase(True)
        service._set_takeoff_curve = _SequenceUseCase(True)
        service._save_annotation_text_properties = _SequenceUseCase(True)
        service._save_annotation_styles = _SequenceUseCase(True)
        service._mutation_executor = SimpleNamespace(
            verify_plan_items_exist=lambda *_args, **_kwargs: None
        )
        service.validate_condition_types_delete = (
            lambda _database_id, condition_type_uids: DeleteValidationResult(
                requested_uids=list(condition_type_uids), blocked_uids=[]
            )
        )
        service.validate_condition_folder_delete = (
            lambda _database_id, _bid_uid, folder_uids: DeleteValidationResult(
                requested_uids=list(folder_uids), blocked_uids=[]
            )
        )
        service._mutation_calls = []
        service._mutation_records = []

        def execute_mutation(database_id, resources, operation, **options):
            service._mutation_calls.append((database_id, resources, options))
            recorder = _Recorder()
            value = operation(recorder)
            service._mutation_records.extend(recorder.records)
            return DatabaseMutationResult(
                operation_id=options["operation_id"],
                outcome_status=MutationOutcomeStatus.COMMITTED,
                value=value,
                commit_attempted=True,
            )

        service._execute_database_mutation = execute_mutation
        return service, provider

    def test_project_commands_defer_exact_write_arguments_to_collaboration_queue(self):
        command_cases = (
            (
                "delete_pages",
                lambda service: service.queue_pages_delete(
                    "database", "7", ["page-1"], lambda _result: None
                ),
                "_delete_pages",
            ),
            (
                "insert_layer",
                lambda service: service.queue_layer_insert(
                    "database", "7", "Layer", 2, lambda _result: None
                ),
                "_insert_layer",
            ),
            (
                "delete_layers",
                lambda service: service.queue_layer_delete(
                    "database", "7", "layer-1", lambda _result: None
                ),
                "_delete_layer",
            ),
            (
                "swap_layers",
                lambda service: service.queue_layer_reorder(
                    "database",
                    "7",
                    "layer-1",
                    "layer-2",
                    lambda _result: None,
                ),
                "_swap_layer_sequence",
            ),
            (
                "rename_layer",
                lambda service: service.queue_layer_rename(
                    "database", "7", "layer-1", "Renamed", lambda _result: None
                ),
                "_update_layer_name",
            ),
            (
                "update_all_layers_show",
                lambda service: service.queue_all_layers_show(
                    "database",
                    "7",
                    False,
                    ["70", "71"],
                    lambda _result: None,
                ),
                "_update_all_layers_show",
            ),
            (
                "create_condition",
                lambda service: service.queue_condition_create(
                    "database",
                    "7",
                    CreateConditionSpec(name="Condition"),
                    lambda _result: None,
                ),
                "_insert_condition",
            ),
            (
                "delete_conditions",
                lambda service: service.queue_conditions_delete(
                    "database", "7", ["condition-1"], lambda _result: None
                ),
                "_delete_conditions",
            ),
            (
                "duplicate_conditions",
                lambda service: service.queue_conditions_duplicate(
                    "database", "7", ["condition-1"], lambda _result: None
                ),
                "_duplicate_conditions",
            ),
            (
                "update_conditions",
                lambda service: service.queue_conditions_update(
                    "database",
                    "7",
                    ["condition-1"],
                    {"name": "Renamed"},
                    lambda _result: None,
                ),
                "_update_condition",
            ),
            (
                "renumber_conditions",
                lambda service: service.queue_conditions_renumber(
                    "database", "7", ["condition-1"], lambda _result: None
                ),
                "_renumber_conditions",
            ),
            (
                "create_condition_folder",
                lambda service: service.queue_condition_folder_create(
                    "database", "7", "Folder", None, lambda _result: None
                ),
                "_insert_condition_folder",
            ),
            (
                "rename_condition_folder",
                lambda service: service.queue_condition_folder_rename(
                    "database",
                    "7",
                    "folder-1",
                    "Renamed",
                    lambda _result: None,
                ),
                "_rename_condition_folder",
            ),
            (
                "delete_condition_folders",
                lambda service: service.queue_condition_folders_delete(
                    "database", "7", ["folder-1"], lambda _result: None
                ),
                "_delete_condition_folders",
            ),
            (
                "create_project",
                lambda service: service.queue_project_create(
                    "database", "Project", lambda _result: None
                ),
                "_create_project",
            ),
            (
                "create_bid",
                lambda service: service.queue_bid_create(
                    "database",
                    "project-1",
                    {"job_name": "New Bid", "pages": []},
                    lambda _result: None,
                ),
                "_create_bid",
            ),
            (
                "rename_project",
                lambda service: service.queue_project_rename(
                    "database", "project-1", "Renamed", lambda _result: None
                ),
                "_rename_project",
            ),
            (
                "move_bids",
                lambda service: service.queue_bids_move(
                    "database", ["7"], "project-1", lambda _result: None
                ),
                "_move_bids",
            ),
            (
                "duplicate_bids",
                lambda service: service.queue_bids_duplicate(
                    "database", ["7"], "project-1", lambda _result: None
                ),
                "_duplicate_bid",
            ),
            (
                "delete_bids",
                lambda service: service.queue_bids_delete(
                    "database", ["7"], lambda _result: None
                ),
                "_delete_bids",
            ),
            (
                "delete_projects",
                lambda service: service.queue_projects_delete(
                    "database", ["project-1"], lambda _result: None
                ),
                "_delete_projects",
            ),
            (
                "update_bid_job_status",
                lambda service: service.queue_bid_job_status_update(
                    "database", "7", "status-1", lambda _result: None
                ),
                "_update_bid_job_status",
            ),
            (
                "save_condition_types",
                lambda service: service.queue_condition_types_save(
                    "database",
                    {
                        "new": [{"uid": "new_condition_type", "name": "Concrete"}],
                        "updated": [],
                        "deleted_uids": [],
                    },
                    lambda _result: None,
                ),
                "_save_condition_types",
            ),
            (
                "save_cover_sheet",
                lambda service: service.queue_cover_sheet_save(
                    "database",
                    "7",
                    {"job_name": "Renamed", "pages": []},
                    lambda _result: None,
                ),
                "_save_cover_sheet",
            ),
            (
                "save_default_layers",
                lambda service: service.queue_default_layer_insert(
                    "database", "Default", 0, lambda _result: None
                ),
                "_insert_layer",
            ),
            (
                "save_default_layers",
                lambda service: service.queue_default_layers_delete(
                    "database", ["default-1"], lambda _result: None
                ),
                "_delete_layer",
            ),
            (
                "save_default_layers",
                lambda service: service.queue_default_layer_update(
                    "database",
                    "show",
                    {"layer_uid": "default-1", "show": False},
                    lambda _result: None,
                ),
                "_update_layer_show",
            ),
            (
                "save_job_statuses",
                lambda service: service.queue_job_statuses_save(
                    "database",
                    {
                        "new": [{"uid": "new_status", "name": "Open"}],
                        "updated": [],
                        "deleted_uids": [],
                    },
                    lambda _result: None,
                ),
                "_save_job_statuses",
            ),
            (
                "save_employees",
                lambda service: service.queue_employees_save(
                    "database",
                    {
                        "new": [Employee(uid="new_employee")],
                        "updated": [],
                        "deleted_uids": [],
                    },
                    lambda _result: None,
                ),
                "_save_employees",
            ),
            (
                "save_pay_classes",
                lambda service: service.queue_pay_classes_save(
                    "database",
                    {
                        "new": [{"uid": "new_pay_class", "name": "Field"}],
                        "updated": [],
                        "deleted_uids": [],
                    },
                    lambda _result: None,
                ),
                "_save_pay_classes",
            ),
        )
        expected_arguments = {
            ("delete_pages", "_delete_pages"): ("database", ["page-1"]),
            ("insert_layer", "_insert_layer"): ("database", "7", "Layer", 2),
            ("delete_layers", "_delete_layer"): ("database", "layer-1"),
            ("swap_layers", "_swap_layer_sequence"): ("database", "layer-1", "layer-2"),
            ("rename_layer", "_update_layer_name"): ("database", "layer-1", "Renamed"),
            ("update_all_layers_show", "_update_all_layers_show"): (
                "database",
                "7",
                False,
                ["70", "71"],
            ),
            ("create_condition", "_insert_condition"): (
                "database",
                "7",
                CreateConditionSpec(name="Condition"),
            ),
            ("delete_conditions", "_delete_conditions"): (
                "database",
                "7",
                ["condition-1"],
            ),
            ("duplicate_conditions", "_duplicate_conditions"): (
                "database",
                "7",
                ["condition-1"],
            ),
            ("update_conditions", "_update_condition"): (
                "database",
                "7",
                "condition-1",
                UpdateConditionDto({"name": "Renamed"}),
            ),
            ("renumber_conditions", "_renumber_conditions"): (
                "database",
                "7",
                ["condition-1"],
            ),
            ("create_condition_folder", "_insert_condition_folder"): (
                "database",
                "7",
                "Folder",
                None,
            ),
            ("rename_condition_folder", "_rename_condition_folder"): (
                "database",
                "folder-1",
                "Renamed",
            ),
            ("delete_condition_folders", "_delete_condition_folders"): (
                "database",
                ["folder-1"],
            ),
            ("create_project", "_create_project"): ("database", "Project"),
            ("create_bid", "_create_bid"): (
                "database",
                "project-1",
                {"job_name": "New Bid", "pages": []},
            ),
            ("rename_project", "_rename_project"): ("database", "project-1", "Renamed"),
            ("move_bids", "_move_bids"): ("database", ["7"], "project-1", None),
            ("duplicate_bids", "_duplicate_bid"): ("database", "7"),
            ("delete_bids", "_delete_bids"): ("database", ["7"]),
            ("delete_projects", "_delete_projects"): ("database", ["project-1"]),
            ("update_bid_job_status", "_update_bid_job_status"): (
                "database",
                "7",
                "status-1",
            ),
            ("save_condition_types", "_save_condition_types"): (
                "database",
                {
                    "new": [{"uid": "new_condition_type", "name": "Concrete"}],
                    "updated": [],
                    "deleted_uids": [],
                },
            ),
            ("save_cover_sheet", "_save_cover_sheet"): (
                "database",
                "7",
                {"job_name": "Renamed", "pages": []},
            ),
            ("save_default_layers", "_insert_layer"): ("database", "Default", 0),
            ("save_default_layers", "_delete_layer"): ("database", "default-1"),
            ("save_default_layers", "_update_layer_show"): (
                "database",
                "default-1",
                False,
            ),
            ("save_job_statuses", "_save_job_statuses"): (
                "database",
                {
                    "new": [{"uid": "new_status", "name": "Open"}],
                    "updated": [],
                    "deleted_uids": [],
                },
            ),
            ("save_employees", "_save_employees"): (
                "database",
                {
                    "new": [Employee(uid="new_employee")],
                    "updated": [],
                    "deleted_uids": [],
                },
            ),
            ("save_pay_classes", "_save_pay_classes"): (
                "database",
                {
                    "new": [{"uid": "new_pay_class", "name": "Field"}],
                    "updated": [],
                    "deleted_uids": [],
                },
            ),
        }
        self.assertEqual(
            set(expected_arguments),
            {(kind, name) for kind, _submit, name in command_cases},
        )
        for write_kind, submit, use_case_name in command_cases:
            with self.subTest(write_kind=write_kind):
                service, provider = self._queued_project_service()
                sequence = submit(service)
                self.assertEqual(sequence, 41)
                self.assertEqual(len(provider.requests), 1)
                use_case = getattr(service, use_case_name)
                self.assertEqual(use_case.calls, [])
                self.assertEqual(service._mutation_calls, [])
                request, execute, _callback = provider.requests[0]
                self.assertIsInstance(request.payload, ProjectWritePayload)
                self.assertEqual(request.database_id, "database")
                self.assertEqual(request.payload.write_kind, write_kind)
                if write_kind == "update_all_layers_show":
                    self.assertEqual(
                        request.payload.values_json,
                        '{"layer_uids":["70","71"],"show":false}',
                    )
                result = execute()
                self.assertEqual(result.outcome_status, MutationOutcomeStatus.COMMITTED)
                self.assertEqual(
                    use_case.calls, [expected_arguments[(write_kind, use_case_name)]]
                )
                self.assertEqual(len(service._mutation_calls), 1)
                database, resources, options = service._mutation_calls[0]
                self.assertEqual(database, "database")
                self.assertEqual(
                    set(resources),
                    set(request.resources) | set(request.dependency_resources),
                )
                self.assertEqual(options["operation_id"], request.operation_id)
                self.assertEqual(options["request_hash"], request.request_hash)
                self.assertFalse(options["publish_conflict_event"])
                self.assertIsNotNone(result.authoritative_result)
                self.assertTrue(service._mutation_records)
                if write_kind == "duplicate_bids":
                    self.assertEqual(
                        service._move_bids.calls,
                        [("database", ["8"], "project-1", None)],
                    )
                    self.assertEqual(
                        result.authoritative_result.created_uid_maps,
                        (("bids", (("7", "8"),)),),
                    )

    def test_queued_bulk_layer_visibility_rejects_a_bid_switch(self):
        service = ProjectWriteService.__new__(ProjectWriteService)
        service.uses_sql_collaboration_mutations = lambda _database_id: True
        service._active_bid_uid_for = lambda _database_id: 8
        service.queue_all_layers_show = lambda *_args, **_kwargs: self.fail(
            "a captured Bid 7 operation must not write to active Bid 8"
        )
        self.assertFalse(
            service.queue_page_setting_if_sql(
                "database",
                "7",
                "all_layers_show",
                [False],
            )
        )

    def test_sql_mixed_delete_removes_endpoint_annotation_before_takeoff_cascade(self):
        service, provider = self._queued_project_service()
        call_order = []

        class DeleteAnnotations:
            def execute(self, _database_id, annotations):
                call_order.append(("annotations", list(annotations)))
                return True

        class DeleteTakeoffs:
            def execute(self, _database_id, takeoff_uids):
                call_order.append(("takeoffs", list(takeoff_uids)))
                return True

        service._delete_annotations = DeleteAnnotations()
        service._delete_takeoffs = DeleteTakeoffs()
        service.queue_plan_items_delete(
            "database",
            "7",
            ["takeoff-1"],
            [("line-1", "line")],
            lambda _result: None,
        )
        result = provider.requests[-1][1]()
        self.assertEqual(result.outcome_status, MutationOutcomeStatus.COMMITTED)
        self.assertEqual(
            call_order,
            [
                ("annotations", [("line-1", "line")]),
                ("takeoffs", ["takeoff-1"]),
            ],
        )

    def test_sql_property_replay_restores_distinct_original_areas(self):
        service, provider = self._queued_project_service()
        service._save_takeoffs_area = _SequenceUseCase(True, True)
        service._project_data.get_current_bid_ref = lambda: BidRef("database", "7")
        service._project_data.get_all_takeoffs = lambda: [
            Takeoff(uid=uid, page_uid="20", condition_uid="30")
            for uid in ("takeoff-1", "takeoff-2")
        ]
        from ost_visualizer.application.dtos.collaboration_dtos import (
            ConcurrencyToken,
            ExpectedResourceVersion,
        )

        service._concurrency_tokens = SimpleNamespace(
            expected_versions=lambda _database, resources: tuple(
                ExpectedResourceVersion(resource, ConcurrencyToken(b"a" * 8))
                for resource in resources
            )
        )
        service.queue_plan_properties(
            "database",
            "7",
            "takeoff_area",
            [("takeoff-1", "area-1"), ("takeoff-2", "area-2")],
            lambda _result: None,
        )
        result = provider.requests[-1][1]()
        self.assertEqual(result.outcome_status, MutationOutcomeStatus.COMMITTED)
        self.assertEqual(
            service._save_takeoffs_area.calls,
            [
                ("database", ["takeoff-1"], "area-1"),
                ("database", ["takeoff-2"], "area-2"),
            ],
        )

    def test_sql_condition_update_records_name_encoded_elevation_fields(self):
        service, provider = self._queued_project_service()
        service._project_data.get_bid_conditions = lambda: {
            "condition-1": Condition(uid="condition-1", name="Walls @T 10' - 0\"")
        }
        recorded_fields = []

        class Recorder:
            def record(self, _resource, _operation, *, changed_fields=(), **_kwargs):
                recorded_fields.append(changed_fields)

        service.queue_conditions_update(
            "database",
            "7",
            ["condition-1"],
            {"name": "Walls @B 8' - 0\""},
            lambda _result: None,
        )
        _request, execute, _callback = provider.requests[0]
        service._execute_database_mutation = (
            lambda database_id, resources, operation, **options: DatabaseMutationResult(
                operation_id=options["operation_id"],
                outcome_status=MutationOutcomeStatus.COMMITTED,
                value=operation(Recorder()),
                commit_attempted=True,
            )
        )
        result = execute()
        self.assertEqual(result.outcome_status, MutationOutcomeStatus.COMMITTED)
        self.assertEqual(recorded_fields, [("is_top", "name", "z_value")])

    def test_sql_condition_editor_update_transfers_its_owned_lease(self):
        service, provider = self._queued_project_service()
        edited = ResourceRef("condition", "condition-1", 7)
        navigable = ResourceRef("condition", "condition-2", 7)
        handle = EditLeaseHandle(
            database_id="database",
            draft_id="condition-editor",
            runtime_generation=3,
            operation_id="edit-condition-dialog",
            owning_surface="condition-sidebar",
            resources=(edited, navigable),
        )
        service.queue_conditions_update(
            "database",
            "7",
            ["condition-1"],
            {"name": "Renamed"},
            lambda _result: None,
            edit_lease_handle=handle,
        )
        request, _execute, _callback = provider.requests[0]
        self.assertEqual(request.resources, (edited,))
        self.assertIs(request.edit_lease_handle, handle)
        self.assertEqual(_execute().outcome_status, MutationOutcomeStatus.COMMITTED)
        self.assertEqual(
            service._update_condition.calls,
            [("database", "7", "condition-1", UpdateConditionDto({"name": "Renamed"}))],
        )

    def test_sql_master_data_update_transfers_collection_dialog_lease(self):
        service, provider = self._queued_project_service()
        collection = ResourceRef("job_statuses_collection", "database")
        edited = ResourceRef("job_status", "status-1")
        handle = EditLeaseHandle(
            database_id="database",
            draft_id="job-status-editor",
            runtime_generation=3,
            operation_id="job-status-dialog",
            owning_surface="main-window-dialog",
            resources=(collection, edited),
        )
        service.queue_job_statuses_save(
            "database",
            {
                "new": [],
                "updated": [{"uid": "status-1", "name": "Awarded"}],
                "deleted_uids": [],
            },
            lambda _result: None,
            edit_lease_handle=handle,
        )
        request, _execute, _callback = provider.requests[0]
        self.assertEqual(request.resources, (edited,))
        self.assertEqual(request.owning_surface, "main-window-dialog")
        self.assertIs(request.edit_lease_handle, handle)
        self.assertEqual(_execute().authoritative_result.updated_resources, (edited,))
        self.assertEqual(
            service._save_job_statuses.calls,
            [
                (
                    "database",
                    {
                        "new": [],
                        "updated": [{"uid": "status-1", "name": "Awarded"}],
                        "deleted_uids": [],
                    },
                )
            ],
        )

    def test_sql_cover_sheet_save_transfers_aggregate_dialog_lease(self):
        service, provider = self._queued_project_service()
        cover_sheet = ResourceRef("cover_sheet", "7", 7)
        bid = ResourceRef("bid", "7", 7)
        handle = EditLeaseHandle(
            database_id="database",
            draft_id="cover-sheet-editor",
            runtime_generation=3,
            operation_id="cover-sheet-dialog",
            owning_surface="main-window-dialog",
            resources=(cover_sheet, bid),
        )
        service.queue_cover_sheet_save(
            "database",
            "7",
            {"notes": "Updated"},
            lambda _result: None,
            edit_lease_handle=handle,
        )
        request, _execute, _callback = provider.requests[0]
        self.assertEqual(request.resources, (cover_sheet,))
        self.assertEqual(request.owning_surface, "main-window-dialog")
        self.assertIs(request.edit_lease_handle, handle)
        self.assertEqual(_execute().outcome_status, MutationOutcomeStatus.COMMITTED)
        self.assertEqual(
            service._save_cover_sheet.calls, [("database", "7", {"notes": "Updated"})]
        )

    def test_sql_new_bid_transfers_cover_sheet_lease_and_tracks_target_project(self):
        service, provider = self._queued_project_service()
        target = ResourceRef("project_bids", "project-1")
        master = ResourceRef("job_status", "status-1")
        handle = EditLeaseHandle(
            database_id="database",
            draft_id="new-project-cover-sheet",
            runtime_generation=3,
            operation_id="new-project-cover-sheet-dialog",
            owning_surface="main-window-dialog",
            resources=(target, master),
        )
        service.queue_bid_create(
            "database",
            "project-1",
            {"job_status_uid": "status-1", "pages": []},
            lambda _result: None,
            edit_lease_handle=handle,
        )
        request, _execute, _callback = provider.requests[0]
        self.assertEqual(request.resources, (target,))
        self.assertIn(ResourceRef("project", "project-1"), request.dependency_resources)
        self.assertEqual(request.owning_surface, "main-window-dialog")
        self.assertIs(request.edit_lease_handle, handle)
        self.assertEqual(
            _execute().authoritative_result.created_uid_maps, (("bids", (("0", "8"),)),)
        )
        self.assertEqual(
            service._create_bid.calls,
            [("database", "project-1", {"job_status_uid": "status-1", "pages": []})],
        )

    def test_sql_page_rename_transfers_navigable_page_dialog_lease(self):
        service, provider = self._queued_project_service()
        first = ResourceRef("page", "page-1", 7)
        second = ResourceRef("page", "page-2", 7)
        handle = EditLeaseHandle(
            database_id="database",
            draft_id="rename-page-editor",
            runtime_generation=3,
            operation_id="rename-page-dialog",
            owning_surface="main-window-dialog",
            resources=(first, second),
        )
        service.queue_page_settings(
            "database",
            "7",
            "name",
            [["page-2", "Renamed"]],
            lambda _result: None,
            edit_lease_handle=handle,
        )
        request, _execute, _callback = provider.requests[0]
        self.assertEqual(request.resources, (second,))
        self.assertEqual(request.owning_surface, "main-window-dialog")
        self.assertIs(request.edit_lease_handle, handle)
        self.assertEqual(
            _execute().authoritative_result.affected_page_uids, ("page-2",)
        )
        self.assertEqual(
            service._save_page_name.calls, [("database", "page-2", "Renamed")]
        )

    def test_empty_mdb_master_data_changes_skip_write_and_hierarchy_reload(self):
        service = ProjectWriteService.__new__(ProjectWriteService)
        service._execute_database_mutation = lambda *_args, **_kwargs: self.fail(
            "an empty changeset must not open a database mutation"
        )
        service.reload_and_notify = lambda *_args, **_kwargs: self.fail(
            "an empty changeset must not rebuild the hierarchy"
        )
        empty = {"new": [], "updated": [], "deleted_uids": []}
        self.assertEqual(service.save_job_statuses("database.mdb", empty), {})
        self.assertEqual(service.save_pay_classes("database.mdb", empty), {})


class QueuedProjectSnapshotTests(unittest.TestCase):
    def _run_request(self, provider):
        self.assertEqual(len(provider.requests), 1)
        request, execute, _callback = provider.requests[0]
        payload_hash = request.request_hash
        result = execute()
        self.assertEqual(result.outcome_status, MutationOutcomeStatus.COMMITTED)
        self.assertTrue(result.commit_attempted)
        self.assertEqual(request.request_hash, payload_hash)
        return request, result.authoritative_result

    def test_bid_creation_writes_captured_values_and_master_dependencies(self):
        service, provider = MdbSqlBehaviorParityTests._queued_project_service()
        updates = {"job_name": "Captured", "estimator_uid": "employee-1"}
        expected = deepcopy(updates)
        service.queue_bid_create("database", "project-1", updates, lambda _r: None)
        request = provider.requests[0][0]
        self.assertEqual(service._create_bid.calls, [])
        self.assertIn(
            ResourceRef("employee", "employee-1"), request.dependency_resources
        )
        updates.update(job_name="Later", estimator_uid="employee-2")
        _, result = self._run_request(provider)
        self.assertEqual(
            service._create_bid.calls, [("database", "project-1", expected)]
        )
        self.assertEqual(result.created_uid_maps, (("bids", (("0", "8"),)),))
        self.assertEqual(json.loads(request.payload.values_json)["updates"], expected)

    def test_cover_sheet_writes_captured_nested_pages_and_reports_the_same_scope(self):
        service, provider = MdbSqlBehaviorParityTests._queued_project_service()
        updates = {
            "job_name": "Captured",
            "estimator_uid": "employee-1",
            "pages": [{"uid": "42", "name": "Original page"}],
            "deleted_page_uids": ["43"],
        }
        expected = deepcopy(updates)
        service.queue_cover_sheet_save("database", "7", updates, lambda _r: None)
        self.assertEqual(service._save_cover_sheet.calls, [])
        updates["pages"][0].update(uid="99", name="Later page")
        updates["pages"].append({"uid": "100", "name": "Unsubmitted"})
        updates["deleted_page_uids"].append("101")
        updates["estimator_uid"] = "employee-2"
        request, result = self._run_request(provider)
        self.assertEqual(service._save_cover_sheet.calls, [("database", "7", expected)])
        self.assertEqual(result.affected_page_uids, ("43", "42"))
        self.assertEqual(json.loads(request.payload.values_json), expected)
        self.assertIn(
            ResourceRef("employee", "employee-1"), request.dependency_resources
        )
        self.assertNotIn(
            ResourceRef("employee", "employee-2"), request.dependency_resources
        )

    def test_condition_creation_snapshots_spec_and_foreign_keys(self):
        service, provider = MdbSqlBehaviorParityTests._queued_project_service()
        spec = CreateConditionSpec(name="Captured", layer_uid="10", folder_uid="20")
        expected = deepcopy(spec)
        service.queue_condition_create("database", "7", spec, lambda _r: None)
        self.assertEqual(service._insert_condition.calls, [])
        spec.name, spec.layer_uid, spec.folder_uid = "Later", "11", "21"
        request, result = self._run_request(provider)
        self.assertEqual(service._insert_condition.calls, [("database", "7", expected)])
        self.assertEqual(
            json.loads(request.payload.values_json)["spec"], asdict(expected)
        )
        self.assertEqual(
            set(request.dependency_resources),
            {ResourceRef("layer", "10", 7), ResourceRef("condition_folder", "20", 7)},
        )
        self.assertEqual(result.affected_condition_uids, ("condition-new",))

    def test_condition_updates_snapshot_values_and_target_list(self):
        service, provider = MdbSqlBehaviorParityTests._queued_project_service()
        uids = ["12"]
        changes = {"name": "Captured", "layer_uid": "10"}
        expected = deepcopy(changes)
        service.queue_conditions_update("database", "7", uids, changes, lambda _r: None)
        self.assertEqual(service._update_condition.calls, [])
        uids[:] = ["13"]
        changes.update(name="Later", layer_uid="11")
        request, result = self._run_request(provider)
        self.assertEqual(len(service._update_condition.calls), 1)
        database, bid, uid, dto = service._update_condition.calls[0]
        self.assertEqual((database, bid, uid), ("database", "7", "12"))
        self.assertEqual(dto.get_changes(), expected)
        self.assertEqual(json.loads(request.payload.values_json)["changes"], expected)
        self.assertEqual(request.dependency_resources, (ResourceRef("layer", "10", 7),))
        self.assertEqual(result.updated_resources, (ResourceRef("condition", "12", 7),))

    def test_default_layer_operations_execute_the_captured_intent(self):
        for operation, values, expected_args, select_writer in (
            (
                "rename",
                {"layer_uid": "10", "name": "Captured"},
                ("database", "10", "Captured"),
                lambda s: s._update_layer_name,
            ),
            (
                "show",
                {"layer_uid": "10", "show": False},
                ("database", "10", False),
                lambda s: s._update_layer_show,
            ),
            (
                "show_all",
                {"show": False},
                ("database", False),
                lambda s: s._update_all_layers_show,
            ),
            (
                "reorder",
                {"layer_uid": "10", "neighbor_uid": "11"},
                ("database", "10", "11"),
                lambda s: s._swap_layer_sequence,
            ),
        ):
            with self.subTest(operation=operation):
                service, provider = MdbSqlBehaviorParityTests._queued_project_service()
                expected_payload = {"operation": operation, **values}
                writer = select_writer(service)
                service.queue_default_layer_update(
                    "database", operation, values, lambda _r: None
                )
                self.assertEqual(writer.calls, [])
                values.update(
                    layer_uid="99", neighbor_uid="100", name="Later", show=True
                )
                request, result = self._run_request(provider)
                self.assertEqual(writer.calls, [expected_args])
                self.assertEqual(
                    json.loads(request.payload.values_json), expected_payload
                )
                self.assertEqual(result.affected_families, ("default_layers",))

    def test_catalog_saves_snapshot_nested_dicts_and_mutable_dataclasses(self):
        for family, create_item, mutate_item, select_queue, select_writer, mapping in (
            (
                "condition_types",
                lambda uid: {"uid": uid, "name": "Captured"},
                lambda item: item.update(uid="99", name="Later"),
                lambda s: s.queue_condition_types_save,
                lambda s: s._save_condition_types,
                {"new_condition_type": "type-new"},
            ),
            (
                "job_statuses",
                lambda uid: {"uid": uid, "name": "Captured"},
                lambda item: item.update(uid="99", name="Later"),
                lambda s: s.queue_job_statuses_save,
                lambda s: s._save_job_statuses,
                {"new_status": "status-new"},
            ),
            (
                "employees",
                lambda uid: Employee(uid=uid, first_name="Captured"),
                self._mutate_employee,
                lambda s: s.queue_employees_save,
                lambda s: s._save_employees,
                {"new_employee": "employee-new"},
            ),
            (
                "pay_classes",
                lambda uid: {"uid": uid, "name": "Captured"},
                lambda item: item.update(uid="99", name="Later"),
                lambda s: s.queue_pay_classes_save,
                lambda s: s._save_pay_classes,
                {"new_pay_class": "pay-class-new"},
            ),
        ):
            with self.subTest(family=family):
                service, provider = MdbSqlBehaviorParityTests._queued_project_service()
                changes = {
                    "new": [create_item(next(iter(mapping)))],
                    "updated": [create_item("12")],
                    "deleted_uids": ["13"],
                }
                expected = deepcopy(changes)
                writer = select_writer(service)
                select_queue(service)("database", changes, lambda _r: None)
                self.assertEqual(writer.calls, [])
                mutate_item(changes["updated"][0])
                new_item = changes["new"][0]
                if isinstance(new_item, Employee):
                    new_item.first_name = "Later new employee"
                else:
                    new_item["name"] = "Later new item"
                changes["new"].clear()
                changes["deleted_uids"].append("14")
                request, result = self._run_request(provider)
                self.assertEqual(writer.calls, [("database", expected)])
                self.assertEqual(
                    result.created_uid_maps, ((family, tuple(mapping.items())),)
                )
                self.assertEqual(
                    [r.resource_id for r in result.updated_resources], ["12"]
                )
                self.assertEqual(
                    [r.resource_id for r in result.deleted_resources], ["13"]
                )
                self.assertEqual(
                    json.loads(request.payload.values_json)["deleted_uids"], ["13"]
                )

    @staticmethod
    def _mutate_employee(item):
        item.uid, item.first_name = "99", "Later"


class PlanPropertyHistoryIdentityTests(unittest.TestCase):
    @staticmethod
    def committed(authoritative_result=None):
        return QueuedMutationResult(
            database_id="bid.mdb",
            runtime_generation=3,
            operation_id=str(uuid.uuid4()),
            outcome_status=MutationOutcomeStatus.COMMITTED,
            authoritative_result=authoritative_result,
        )

    def test_queued_area_deletion_invalidates_only_after_confirmed_commit(self):
        for status in (
            MutationOutcomeStatus.COMMITTED,
            MutationOutcomeStatus.COMMITTED_PROJECTION_FAILED,
            MutationOutcomeStatus.REJECTED,
            MutationOutcomeStatus.FAILED_BEFORE_COMMIT,
            MutationOutcomeStatus.COMMIT_STATUS_UNKNOWN,
        ):
            with self.subTest(status=status):
                service = MdbSqlBehaviorParityTests._local_composite_service()
                service._event_bus = _permissions__EventBus()
                queued = []
                service._queue_project_write = (
                    lambda *args, **_kwargs: queued.append(args) or 1
                )
                completed = []
                changes = BidAreaChangeset([], [], ["2"])
                service.queue_bid_areas_save("bid.mdb", "7", changes, completed.append)
                self.assertEqual(service._event_bus.published, [])
                # A dialog's next draft cannot change the already queued deletion.
                changes.deleted_uids.clear()
                result = replace(self.committed(), outcome_status=status)
                queued[0][4](result)
                self.assertEqual(completed, [result])
                if status in (
                    MutationOutcomeStatus.COMMITTED,
                    MutationOutcomeStatus.COMMITTED_PROJECTION_FAILED,
                ):
                    self.assertEqual(
                        service._event_bus.published,
                        [
                            (
                                AppEvents.BID_AREAS_DELETED,
                                {
                                    "database_id": "bid.mdb",
                                    "bid_uid": "7",
                                    "area_uids": ("2",),
                                },
                            )
                        ],
                    )
                else:
                    self.assertEqual(service._event_bus.published, [])

    def test_queued_area_save_persists_the_same_snapshot_as_its_delete_event(self):
        service, provider = MdbSqlBehaviorParityTests._queued_project_service()
        service._event_bus = _permissions__EventBus()
        submitted = BidAreaChangeset(
            [BidArea("draft", "7", "1", "New", 2, "guid")],
            [BidArea("1", "7", "", "Original", 1)],
            ["2"],
        )
        persisted = []
        service._save_bid_areas = SimpleNamespace(
            execute=lambda _db, _bid, changes: persisted.append(changes)
            or {"draft": "4"}
        )
        service.queue_bid_areas_save("database", "7", submitted, lambda _result: None)
        self.assertEqual(persisted, [])
        submitted.deleted_uids[:] = ["3"]
        submitted.updated[0].name = "Later draft"
        submitted.new[0].parent_uid = "3"
        submitted.new[0].guid = "later-guid"
        submitted.new.clear()
        result = provider.requests[-1][1]()
        self.assertEqual(result.outcome_status, MutationOutcomeStatus.COMMITTED)
        self.assertEqual(persisted[0].deleted_uids, ["2"])
        self.assertEqual(persisted[0].updated[0].name, "Original")
        self.assertEqual(
            persisted[0].new, [BidArea("draft", "7", "1", "New", 2, "guid")]
        )
        self.assertEqual(len(persisted), 1)
        self.assertEqual(service._event_bus.published, [])
        request, _execute, completed = provider.requests[0]
        completed(
            QueuedMutationResult(
                database_id="database",
                runtime_generation=1,
                operation_id=request.operation_id,
                outcome_status=result.outcome_status,
                authoritative_result=result.authoritative_result,
                commit_attempted=True,
            )
        )
        self.assertEqual(
            service._event_bus.published,
            [
                (
                    AppEvents.BID_AREAS_DELETED,
                    {"database_id": "database", "bid_uid": "7", "area_uids": ("2",)},
                )
            ],
        )


class QueuedAnnotationSnapshotTests(unittest.TestCase):
    def test_each_family_queue_keeps_geometry_style_and_page_from_submission(self):
        from ost_visualizer.application.dtos.collaboration_dtos import (
            PlanItemsPastePayload,
        )
        from ost_visualizer.application.dtos.collaboration_resource_catalog import (
            annotation_resource_id,
        )
        from ost_visualizer.application.dtos.insert_annotation_spec_dto import (
            InsertAnnotationSpec,
        )

        for (
            kind,
            position,
        ) in ANNOTATION_POSITIONS.items():
            with self.subTest(kind=kind):
                service, provider = MdbSqlBehaviorParityTests._queued_project_service()
                service._insert_annotations = _SequenceUseCase(["new"])
                spec = InsertAnnotationSpec(
                    page_uid="p1",
                    annotation_type=kind,
                    position=list(position),
                    color="#123456",
                    width=2.0,
                    properties={"Text": "Before"},
                )
                payload = PlanItemsPastePayload(
                    source_bid_uid="7",
                    destination_bid_uid="7",
                    annotation_source_uids=(annotation_resource_id(kind, "1"),),
                    annotation_specs=(spec,),
                )
                service.queue_plan_items_paste("database", payload, lambda _: None)
                request, execute, _callback = provider.requests[0]
                spec.page_uid = "p2"
                spec.position[0] = 999.0
                spec.properties["Text"] = "After"
                spec.color = "#ffffff"
                result = execute()
                self.assertEqual(result.outcome_status, MutationOutcomeStatus.COMMITTED)
                self.assertEqual(
                    result.authoritative_result.affected_page_uids, ("p1",)
                )
                self.assertEqual(len(service._insert_annotations.calls), 1)
                captured = service._insert_annotations.calls[0][2][0]
                self.assertEqual(captured.page_uid, "p1")
                self.assertEqual(captured.position, position)
                self.assertEqual(captured.properties["Text"], "Before")
                self.assertEqual(captured.color, "#123456")
                self.assertEqual(captured.width, 2.0)
                self.assertEqual(
                    result.authoritative_result.created_uid_maps,
                    (
                        ("takeoffs", ()),
                        ("annotations", ((annotation_resource_id(kind, "1"), "new"),)),
                        ("conditions", ()),
                    ),
                )
                self.assertEqual(
                    request.payload.annotation_specs[0].page_uid, request.page_uid
                )


# --- Second-pass contract harness -------------------------------------------------
# The real ProjectWriteService constructor is wired with recording use-case doubles so
# that every command's backend routing, mutation-boundary request (resources, lock
# flags), recorded changes, authoritative result and refresh side effects are pinned
# as text. The doubles record the *method name* too, so a renamed or mis-wired use case
# cannot pass. The executor, session registry and token service are the same strict
# fakes used by test_base_write_service (they enforce nothing a real SQL writer would:
# versions, leases and transactions are covered by the SQL writer tests, not here).
_USE_CASE_NAMES = (
    "delete_bids",
    "delete_projects",
    "create_project",
    "rename_project",
    "move_bids",
    "duplicate_bid",
    "create_bid",
    "delete_conditions",
    "duplicate_conditions",
    "update_condition",
    "renumber_conditions",
    "insert_condition",
    "insert_condition_folder",
    "rename_condition_folder",
    "delete_condition_folders",
    "save_takeoff_positions",
    "save_takeoff_rotations",
    "save_takeoff_text_properties",
    "save_takeoffs_area",
    "save_takeoffs_condition",
    "set_takeoffs_negative",
    "set_takeoff_curve",
    "insert_takeoffs",
    "delete_takeoffs",
    "delete_pages",
    "save_cover_sheet",
    "update_bid_job_status",
    "save_job_statuses",
    "save_bid_areas",
    "save_page_name",
    "save_page_scale",
    "save_page_show_mode",
    "save_page_overlay_image",
    "save_page_overlay_rect",
    "save_page_invert",
    "save_page_bitonal",
    "save_page_image_adjustments",
    "save_page_area",
    "save_employees",
    "save_pay_classes",
    "save_condition_types",
    "update_layer_show",
    "update_all_layers_show",
    "update_layer_name",
    "insert_layer",
    "delete_layer",
    "swap_layer_sequence",
    "save_bid_selected_page",
    "save_page_view_state",
    "delete_annotations",
    "insert_annotations",
    "save_annotation_positions",
    "save_annotation_text_properties",
    "save_annotation_styles",
)


class _Seq:
    """Scripted return values consumed one per call (last value repeats)."""

    def __init__(self, *values):
        self.values = list(values)

    def next(self):
        return self.values.pop(0) if len(self.values) > 1 else self.values[0]


class _UseCaseProbe:
    def __init__(self, name, calls, results):
        self._name, self._calls, self._results = name, calls, results

    def __getattr__(self, method):
        if method.startswith("__"):
            raise AttributeError(method)

        def call(*args, **kwargs):
            self._calls.append((self._name, method, args, kwargs))
            key = (self._name, method)
            result = self._results.get(key, self._results.get(self._name, True))
            if isinstance(result, _Seq):
                result = result.next()
            elif callable(result):
                result = result(*args, **kwargs)
            if isinstance(result, BaseException):
                raise result
            return result

        return call


def _call_text(name, method, args, kwargs):
    def show(value):
        if isinstance(value, UpdateConditionDto):
            return "UpdateConditionDto" + repr(
                dict(sorted(value.get_changes().items()))
            )
        return repr(value)

    rendered = ", ".join(
        [show(arg) for arg in args] + [f"{k}={show(v)}" for k, v in kwargs.items()]
    )
    return f"call {name}.{method}({rendered})"


class _HarnessExecutor(_access__MutationExecutor):
    """Strict executor fake that also records the plan-item preflight it is asked for."""

    def __init__(self):
        super().__init__()
        self.verifications = []
        self.reassignments = []
        self.values = []
        self.commit_attempted = False
        self.consumed_lock_tokens = ()
        self.rejection_reason = None

    def execute(self, request, operation):
        self.calls += 1
        self.requests.append(request)
        # Like both real executors, only a committed mutation yields a value; an
        # uncertain commit has run the operation (its side effects on the caller's
        # result objects already happened) but reports no value.
        committed = self.status == MutationOutcomeStatus.COMMITTED
        unknown = self.status == MutationOutcomeStatus.COMMIT_STATUS_UNKNOWN
        value = operation(self.recorder) if committed or unknown else None
        if not committed:
            value = None
        self.values.append(value)
        return DatabaseMutationResult(
            operation_id=request.operation_id,
            outcome_status=self.status,
            value=value,
            conflict=self.conflict,
            resulting_versions=self.resulting_versions,
            commit_attempted=self.commit_attempted,
            consumed_lock_tokens=self.consumed_lock_tokens,
            rejection_reason=self.rejection_reason,
        )

    def verify_takeoff_reassignment(self, database_id, bid_uid, assignment):
        self.reassignments.append(
            (
                database_id,
                bid_uid,
                (
                    assignment.condition_uid,
                    assignment.page_uid,
                    assignment.takeoff_uids,
                ),
            )
        )

    def verify_plan_items_exist(
        self, database_id, bid_uid, takeoff_uids, annotations, *, takeoff_ownership=()
    ):
        self.verifications.append(
            (
                database_id,
                bid_uid,
                tuple(takeoff_uids),
                tuple(annotations),
                tuple(item.uid for item in takeoff_ownership),
            )
        )


class _HarnessTokens(_access__ConcurrencyTokens):
    """Returns a submission baseline for every requested resource except `missing`."""

    def __init__(self):
        super().__init__()
        self.missing = set()
        self.guard = False

    def expected_versions(self, database_id, resources):
        self.expected_requests.append((database_id, resources))
        if not self.guard:
            return ()
        return tuple(
            ExpectedResourceVersion(resource, ConcurrencyToken(b"\x07" * 8))
            for resource in resources
            if resource not in self.missing
        )


class _HarnessProvider(_CapturedQueueProvider):
    def __init__(self, sql):
        super().__init__()
        self.sql = sql

    def uses_sql_collaboration(self, _database_id):
        return self.sql


class _HarnessProjectData:
    """Active Bid 7 of C:/jobs/test.mdb; the minimal read model the service consults."""

    def __init__(self):
        self.locked = False
        self.bid_ref = BidRef("C:/jobs/test.mdb", "7")
        self.pages = {}
        self.bid = SimpleNamespace(uid="7")
        self.loaded_ref = BidRef("C:/jobs/test.mdb", "7")
        self.project_of_bid = None
        self.page_owners = {}
        self.conditions = {
            "10": Condition(uid="10", condition_type=Condition.TYPE_LINEAR),
            "11": Condition(uid="11", condition_type=Condition.TYPE_LINEAR),
        }
        line = [0.0, 0.0, 10.0, 0.0]
        self.takeoffs = [
            Takeoff(
                uid="30", page_uid="20", condition_uid="10", area_uid="5", position=line
            ),
            Takeoff(
                uid="31",
                page_uid="20",
                condition_uid="10",
                parent_uid="30",
                position=list(line),
            ),
            Takeoff(uid="32", page_uid="21", condition_uid="11", position=list(line)),
        ]

    def is_current_bid_locked(self):
        return self.locked

    def get_current_bid_ref(self):
        return self.bid_ref

    def get_bid(self, bid_ref):
        return self.bid if bid_ref == self.loaded_ref else None

    def get_bid_conditions(self):
        return dict(self.conditions)

    def get_bid_condition_folders(self):
        return {}

    def get_all_takeoffs(self):
        return list(self.takeoffs)

    def get_page(self, page_uid):
        return self.pages.get(page_uid)

    def get_project_bid_uids(self, _database_id, project_uids):
        return [f"{uid}1" for uid in project_uids]

    def get_page_takeoffs(self, page_uid):
        return [SimpleNamespace(uid=f"{page_uid}-t")]

    def get_page_annotations(self, page_uid):
        return [SimpleNamespace(uid=f"{page_uid}-a", annotation_type="rect")]

    def find_project_uid_for_bid(self, _bid_ref):
        return self.project_of_bid

    def find_owning_bid_uid_for_page(self, _database_id, page_uid):
        # The hierarchy's owner of a page (None = the model does not know the page).
        return self.page_owners.get(page_uid)

    def replace_condition_family(self, *_args):
        return False

    def get_bid_layer_snapshot(self):
        return []

    def apply_page_scales(self, _bid_ref, pages, _sf1, _sf2):
        return tuple(page.uid for page in pages)

    def apply_page_name(self, *_args):
        return True


class _Harness:
    DATABASE = "C:/jobs/test.mdb"

    def __init__(self, results=None, *, reload_result=True, editable=True, sql=True):
        self.calls = []
        self.reloads = []
        self.events = _access__EventBus()
        self.data = _HarnessProjectData()
        self.executor = _HarnessExecutor()
        self.tokens = _HarnessTokens()
        self.provider = _HarnessProvider(sql)
        probes = {
            name: _UseCaseProbe(name, self.calls, results or {})
            for name in _USE_CASE_NAMES
        }
        logger = logging.getLogger("test.project_write_harness")
        self.constructor_arguments = dict(
            **probes,
            mutation_executor=self.executor,
            session_registry=_access__SessionRegistry(),
            concurrency_tokens=self.tokens,
            database_capability_service=_access__CapabilityService(editable),
            sql_collaboration_provider=lambda: self.provider,
            condition_family_reader=lambda *_args: ({}, {}),
            condition_type_uids_in_use_provider=lambda _database_id: {"used"},
            reload_database=lambda path: self.reloads.append(path) or reload_result,
            event_bus=self.events,
            logger=logger,
            bid_write_guard=ActiveBidWriteGuard(self.data),
            project_data_service=self.data,
        )
        self.service = ProjectWriteService(**self.constructor_arguments)

    @staticmethod
    def resource_text(resource):
        return f"{resource.resource_type}:{resource.resource_id}@{resource.bid_uid}"

    def record_lines(self):
        # Sorted: a few commands record collection updates while iterating a set, and
        # the order of recorded changes inside one transaction is not a contract.
        return sorted(
            f"record {self.resource_text(resource)} {operation.value}"
            + (f" fields={list(fields)}" if fields else "")
            for resource, operation, fields, _payload in self.executor.recorder.changes
        )

    def authoritative_lines(self, authoritative):
        if authoritative is None:
            return ["authoritative none"]
        return [
            f"created={authoritative.created_resource_ids!r}"
            f" maps={authoritative.created_uid_maps!r}",
            "updated "
            + ",".join(self.resource_text(r) for r in authoritative.updated_resources)
            + " deleted "
            + ",".join(self.resource_text(r) for r in authoritative.deleted_resources),
            f"pages={authoritative.affected_page_uids!r}"
            f" conditions={authoritative.affected_condition_uids!r}"
            f" families={authoritative.affected_families!r}",
        ]

    def local_report(self, result):
        """Everything a local (immediate) command did, as one comparable text."""
        if isinstance(result, MutationExecutionResult):
            lines = [
                f"result outcome={result.outcome_status.value}"
                f" created={result.created_resource_ids!r} message={result.message!r}"
                f" commit_attempted={result.commit_attempted}"
            ] + self.authoritative_lines(result.authoritative_result)
        else:
            lines = [f"result={result!r}"]
        lines += [
            _call_text(name, method, args, kwargs)
            for name, method, args, kwargs in self.calls
        ]
        for request in self.executor.requests:
            lines.append(
                "request "
                + ",".join(self.resource_text(r) for r in request.resources)
                + f" child={request.block_bid_child_locks}"
                + f" editors={request.block_bid_active_editors}"
                + f" type={request.mutation_type}"
            )
        lines += [
            f"verify {verification!r}" for verification in self.executor.verifications
        ]
        lines += [f"reassign {check!r}" for check in self.executor.reassignments]
        lines += [f"value {value!r}" for value in self.executor.values]
        lines += self.record_lines()
        lines += [f"reload {path}" for path in self.reloads]
        for event, payload in self.events.published:
            lines.append(f"event {event.__name__} {payload!r}")
        return "\n".join(lines)

    def queue_report(self, execute_result=None):
        """The queued request, then (after running its work) everything the work did."""
        request, execute, _callback = self.provider.requests[-1]
        text = [
            f"request {request.mutation_type.value} surface={request.owning_surface}"
            f" bid={request.bid_uid} page={request.page_uid!r}",
            "resources " + ",".join(self.resource_text(r) for r in request.resources),
            "dependencies "
            + ",".join(self.resource_text(r) for r in request.dependency_resources),
            (
                f"payload {request.payload.write_kind} {request.payload.values_json}"
                if hasattr(request.payload, "write_kind")
                else f"payload {request.payload!r}"
            ),
            f"lease={request.edit_lease_handle is not None}",
        ]
        before = len(self.calls)
        execution = execute()
        text.append(f"outcome {execution.outcome_status.value}")
        executed = self.executor.requests[-1]
        text.append(
            "executed "
            + ",".join(self.resource_text(r) for r in executed.resources)
            + f" child={executed.block_bid_child_locks}"
            + f" editors={executed.block_bid_active_editors}"
            + f" type={executed.mutation_type}"
            + f" id_ok={executed.operation_id == request.operation_id}"
            + f" hash_ok={executed.request_hash == request.request_hash}"
        )
        if executed.expected_versions:
            text.append(
                "baseline "
                + ",".join(
                    self.resource_text(item.resource)
                    for item in executed.expected_versions
                )
            )
        text += [
            f"verify {verification!r}" for verification in self.executor.verifications
        ]
        text += [f"reassign {check!r}" for check in self.executor.reassignments]
        for name, method, args, kwargs in self.calls[before:]:
            text.append(_call_text(name, method, args, kwargs))
        text += [f"value {value!r}" for value in self.executor.values]
        text += self.record_lines()
        text += self.authoritative_lines(execution.authoritative_result)
        return "\n".join(text)


def _area_changes():
    return BidAreaChangeset(
        new=[BidArea(uid="new_0", bid_uid="7", parent_uid="0", name="N", sequence=1)],
        updated=[BidArea(uid="5", bid_uid="7", parent_uid="0", name="U", sequence=2)],
        deleted_uids=["6"],
    )


def _local_rows(d=_Harness.DATABASE):
    """(label, scripted use-case results, command(service)) for Access commands."""
    return (
        ("delete_bids", {}, lambda s: s.delete_bids(d, ["7", "8"])),
        ("delete_bids without refresh", {}, lambda s: s.delete_bids(d, ["7"], False)),
        ("delete_bids empty", {}, lambda s: s.delete_bids(d, [])),
        ("delete_projects", {}, lambda s: s.delete_projects(d, ["3", "4"])),
        (
            "create_project_result",
            {"create_project": "9"},
            lambda s: s.create_project_result(d, "North"),
        ),
        ("rename_project", {}, lambda s: s.rename_project(d, "3", "Renamed")),
        ("move_bids", {}, lambda s: s.move_bids(d, ["7", "8"], "4", "3")),
        (
            "move_bids to orphan",
            {},
            lambda s: s.move_bids(d, ["7"], None, None, False),
        ),
        (
            "duplicate_bid_result",
            {"duplicate_bid": "12"},
            lambda s: s.duplicate_bid_result(d, "7"),
        ),
        (
            "duplicate_bid_result without reload",
            {"duplicate_bid": "12"},
            lambda s: s.duplicate_bid_result(d, "7", reload=False),
        ),
        (
            "create_bid_result",
            {"create_bid": "13"},
            lambda s: s.create_bid_result(d, "3", {"job_name": "B"}),
        ),
        (
            "create_bid_result orphan",
            {"create_bid": "13"},
            lambda s: s.create_bid_result(d, None, {}),
        ),
        ("delete_conditions", {}, lambda s: s.delete_conditions(d, "7", ["c1", "c2"])),
        (
            "create_condition_folder_result",
            {"insert_condition_folder": "f9"},
            lambda s: s.create_condition_folder_result(d, "7", "Walls", "f1"),
        ),
        (
            "rename_condition_folder",
            {},
            lambda s: s.rename_condition_folder(d, "f1", "N"),
        ),
        (
            "duplicate_conditions_result",
            {"duplicate_conditions": ["c9", "c10"]},
            lambda s: s.duplicate_conditions_result(d, "7", ["c1", "", "c1", "c2"]),
        ),
        (
            "duplicate_conditions_to_bid",
            {("duplicate_conditions", "execute_to_bid"): {"c1": "c9", "c2": "c10"}},
            lambda s: s.duplicate_conditions_to_bid(d, "7", "8", ["c1", "c2"]),
        ),
        (
            "renumber_conditions",
            {},
            lambda s: s.renumber_conditions(d, "7", ["c2", "c1"]),
        ),
        (
            "set_takeoff_curve",
            {},
            lambda s: s.set_takeoff_curve(d, "30", [1.0, 2.0], 3),
        ),
        (
            "save_takeoff_positions",
            {},
            lambda s: s.save_takeoff_positions(
                d, [("30", [1.0, 2.0]), ("31", [3.0, 4.0])]
            ),
        ),
        (
            "save_takeoff_rotations",
            {},
            lambda s: s.save_takeoff_rotations(d, [("30", 90.0)]),
        ),
        (
            "save_takeoff_text_properties",
            {},
            lambda s: s.save_takeoff_text_properties(d, [("30", {"Text": "T"})]),
        ),
        (
            "save_takeoffs_area",
            {},
            lambda s: s.save_takeoffs_area(d, ["30", "31"], "5"),
        ),
        (
            "set_takeoffs_negative",
            {},
            lambda s: s.set_takeoffs_negative(d, ["30", "31"], True),
        ),
        ("delete_takeoffs", {}, lambda s: s.delete_takeoffs(d, ["30", "31"])),
        ("save_page_scale", {}, lambda s: s.save_page_scale(d, "20", 1.0, 96.0)),
        ("save_page_name", {}, lambda s: s.save_page_name(d, "20", "Sheet")),
        (
            "save_page_scales",
            {},
            lambda s: s.save_page_scales(d, ["20", "", "21", "20"], 1.0, 96.0),
        ),
        ("save_page_show_mode", {}, lambda s: s.save_page_show_mode(d, "20", 2)),
        (
            "save_page_show_mode without refresh",
            {},
            lambda s: s.save_page_show_mode(d, "20", 2, False),
        ),
        (
            "save_page_overlay_image",
            {},
            lambda s: s.save_page_overlay_image(d, "20", "C:/o.png"),
        ),
        (
            "save_page_overlay_rect_result",
            {},
            lambda s: s.save_page_overlay_rect_result(d, "20", (1.0, 2.0, 3.0, 4.0)),
        ),
        (
            "save_page_overlay_rect_result without refresh",
            {},
            lambda s: s.save_page_overlay_rect_result(
                d, "20", (1.0, 2.0, 3.0, 4.0), False
            ),
        ),
        ("save_page_invert", {}, lambda s: s.save_page_invert(d, "20", True)),
        ("save_page_bitonal", {}, lambda s: s.save_page_bitonal(d, "20", True)),
        (
            "save_page_image_adjustments",
            {},
            lambda s: s.save_page_image_adjustments(
                d, ["20", "", "21", "20"], 90, True, False, True, False
            ),
        ),
        ("save_page_area", {}, lambda s: s.save_page_area(d, "20", "5")),
        ("update_layer_show", {}, lambda s: s.update_layer_show(d, "40", False)),
        (
            "insert_layer_result",
            {"insert_layer": "41"},
            lambda s: s.insert_layer_result(d, "7", "Layer", 2),
        ),
        (
            "insert_default_layer_result",
            {("insert_layer", "execute_default"): "42"},
            lambda s: s.insert_default_layer_result(d, "Default", 1),
        ),
        ("delete_layer", {}, lambda s: s.delete_layer(d, "40")),
        ("delete_layers", {}, lambda s: s.delete_layers(d, ["40", "", "41", "40"])),
        (
            "delete_default_layers",
            {},
            lambda s: s.delete_default_layers(d, ["40", "41"]),
        ),
        (
            "update_all_layers_show",
            {},
            lambda s: s.update_all_layers_show(d, "7", False, ["40", "41"]),
        ),
        (
            "update_all_default_layers_show",
            {},
            lambda s: s.update_all_default_layers_show(d, True),
        ),
        (
            "swap_layer_sequence",
            {},
            lambda s: s.swap_layer_sequence(d, "40", "41"),
        ),
        (
            "swap_default_layer_sequence",
            {},
            lambda s: s.swap_default_layer_sequence(d, "40", "41"),
        ),
        ("update_layer_name", {}, lambda s: s.update_layer_name(d, "40", "Walls")),
        (
            "update_default_layer_name",
            {},
            lambda s: s.update_default_layer_name(d, "40", "Walls"),
        ),
        (
            "update_default_layer_show",
            {},
            lambda s: s.update_default_layer_show(d, "40", False),
        ),
        (
            "save_page_view_state",
            {},
            lambda s: s.save_page_view_state(d, "20", 2.0, 3.0, 4.0),
        ),
        (
            "save_bid_selected_page",
            {},
            lambda s: s.save_bid_selected_page(d, "7", "20"),
        ),
        (
            "save_cover_sheet",
            {},
            lambda s: s.save_cover_sheet(d, "7", {"job_name": "N", "bid_no": "2"}),
        ),
        ("delete_pages", {}, lambda s: s.delete_pages(d, ["20", "", "21", "20"])),
        (
            "update_bid_job_status",
            {},
            lambda s: s.update_bid_job_status(d, "7", "2"),
        ),
        (
            "save_job_statuses",
            {"save_job_statuses": {"n": "5"}},
            lambda s: s.save_job_statuses(d, {"new": [{"uid": "n"}]}),
        ),
        (
            "save_employees_result",
            {"save_employees": {"n": "6"}},
            lambda s: s.save_employees_result(d, {"new": [{"uid": "n"}]}),
        ),
        (
            "save_pay_classes",
            {"save_pay_classes": {"n": "7"}},
            lambda s: s.save_pay_classes(d, {"deleted_uids": ["9"]}),
        ),
        (
            "save_job_statuses unchanged",
            {},
            lambda s: s.save_job_statuses(d, {"new": [], "updated": []}),
        ),
        (
            "create_project",
            {"create_project": "9"},
            lambda s: s.create_project(d, "North"),
        ),
        (
            "create_bid",
            {"create_bid": "13"},
            lambda s: s.create_bid(d, "3", {"job_name": "B"}),
        ),
        ("duplicate_bid", {"duplicate_bid": "12"}, lambda s: s.duplicate_bid(d, "7")),
        (
            "insert_layer",
            {"insert_layer": "41"},
            lambda s: s.insert_layer(d, "7", "Layer", 2),
        ),
        (
            "duplicate_conditions",
            {"duplicate_conditions": ["c9", "c10"]},
            lambda s: s.duplicate_conditions(d, "7", ["c1", "c2"]),
        ),
        (
            "insert_takeoffs",
            {"insert_takeoffs": ["101", "102"]},
            lambda s: s.insert_takeoffs(d, "7", _plan_specs()),
        ),
        (
            "insert_takeoffs_result without refresh",
            {"insert_takeoffs": ["101", "102"]},
            lambda s: s.insert_takeoffs_result(d, "7", _plan_specs(), False),
        ),
        (
            "insert_takeoffs_result consistency",
            {"insert_takeoffs": ["101", "102"]},
            lambda s: s.insert_takeoffs_result(
                d,
                "7",
                _plan_specs(),
                consistency_resources=(
                    ResourceRef("page", "21", 7),
                    ResourceRef("condition", "10", 7),
                ),
            ),
        ),
        ("insert_takeoffs empty", {}, lambda s: s.insert_takeoffs(d, "7", [])),
        ("delete_projects empty", {}, lambda s: s.delete_projects(d, [])),
        ("move_bids empty", {}, lambda s: s.move_bids(d, [], "4")),
        ("delete_conditions empty", {}, lambda s: s.delete_conditions(d, "7", [])),
        (
            "delete_conditions without bid",
            {},
            lambda s: s.delete_conditions(d, "", ["c1"]),
        ),
        ("renumber_conditions empty", {}, lambda s: s.renumber_conditions(d, "7", [])),
        ("save_takeoff_positions empty", {}, lambda s: s.save_takeoff_positions(d, [])),
        ("save_takeoff_rotations empty", {}, lambda s: s.save_takeoff_rotations(d, [])),
        (
            "save_takeoff_text_properties empty",
            {},
            lambda s: s.save_takeoff_text_properties(d, []),
        ),
        ("save_takeoffs_area empty", {}, lambda s: s.save_takeoffs_area(d, [], "5")),
        (
            "set_takeoffs_negative empty",
            {},
            lambda s: s.set_takeoffs_negative(d, [], True),
        ),
        ("delete_takeoffs empty", {}, lambda s: s.delete_takeoffs(d, [])),
        (
            "save_takeoffs_condition empty",
            {},
            lambda s: s.save_takeoffs_condition(d, [], "11"),
        ),
        (
            "save_page_scales empty",
            {},
            lambda s: s.save_page_scales(d, ["", ""], 1.0, 96.0),
        ),
        (
            "save_page_image_adjustments empty",
            {},
            lambda s: s.save_page_image_adjustments(
                d, ["", ""], 90, True, False, True, False
            ),
        ),
        ("delete_pages empty", {}, lambda s: s.delete_pages(d, ["", ""])),
        ("delete_layers empty", {}, lambda s: s.delete_layers(d, [])),
        ("delete_default_layers empty", {}, lambda s: s.delete_default_layers(d, [])),
        (
            "update_all_layers_show without layer uids",
            {},
            lambda s: s.update_all_layers_show(d, "7", True),
        ),
        (
            "update_condition",
            {"update_condition": UpdateConditionResultDto(success=True)},
            lambda s: s.update_condition(
                d, "7", "c1", UpdateConditionDto({"name": "Renamed", "z_value": 2.0})
            ),
        ),
        (
            "create_condition_result",
            {"insert_condition": "c9"},
            lambda s: s.create_condition_result(
                d, "7", CreateConditionSpec(name="C", folder_uid="f1")
            ),
        ),
        (
            "delete_condition_folders_result",
            {},
            lambda s: s.delete_condition_folders_result(d, "7", ["f1", "f2"]),
        ),
        (
            "delete_condition_folders",
            {},
            lambda s: s.delete_condition_folders(d, ["f1"]),
        ),
        (
            "save_condition_types_result",
            {"save_condition_types": {"n": "11"}},
            lambda s: s.save_condition_types_result(
                d,
                {
                    "new": [{"uid": "n", "name": "N"}],
                    "updated": [],
                    "deleted_uids": ["9", "8"],
                },
            ),
        ),
        (
            "save_condition_types_result partially blocked",
            {"save_condition_types": {}},
            lambda s: s.save_condition_types_result(
                d, {"new": [], "updated": [], "deleted_uids": ["used", "9"]}
            ),
        ),
        (
            "save_condition_types_result blocked",
            {"save_condition_types": {}},
            lambda s: s.save_condition_types_result(
                d, {"new": [], "updated": [], "deleted_uids": ["used"]}
            ),
        ),
        (
            "save_condition_types_result without refresh",
            {"save_condition_types": {"n": "11"}},
            lambda s: s.save_condition_types_result(
                d, {"new": [{"uid": "n", "name": "N"}]}, False
            ),
        ),
        (
            "save_condition_types_result empty",
            {},
            lambda s: s.save_condition_types_result(d, {}),
        ),
        (
            "save_condition_types",
            {"save_condition_types": {"n": "11"}},
            lambda s: s.save_condition_types(d, {"new": [{"uid": "n", "name": "N"}]}),
        ),
        (
            "delete_condition_types_result",
            {"save_condition_types": {}},
            lambda s: s.delete_condition_types_result(d, ["9"]),
        ),
        (
            "save_bid_areas_result",
            {"save_bid_areas": {"new_0": "9"}},
            lambda s: s.save_bid_areas_result(d, "7", _area_changes()),
        ),
        (
            "save_bid_areas_result without refresh",
            {"save_bid_areas": {"new_0": "9"}},
            lambda s: s.save_bid_areas_result(d, "7", _area_changes(), False),
        ),
        (
            "save_bid_areas_result deletion only",
            {"save_bid_areas": {}},
            lambda s: s.save_bid_areas_result(
                d, "7", BidAreaChangeset(new=[], updated=[], deleted_uids=["6"])
            ),
        ),
        (
            "save_bid_areas_result unchanged",
            {"save_bid_areas": {}},
            lambda s: s.save_bid_areas_result(
                d, "7", BidAreaChangeset(new=[], updated=[], deleted_uids=[])
            ),
        ),
        (
            "save_bid_areas",
            {"save_bid_areas": {"new_0": "9"}},
            lambda s: s.save_bid_areas(d, "7", _area_changes()),
        ),
        (
            "save_employees_result empty",
            {},
            lambda s: s.save_employees_result(d, {"new": [], "updated": []}),
        ),
        (
            "save_employees_result without refresh",
            {"save_employees": {"n": "6"}},
            lambda s: s.save_employees_result(d, {"new": [{"uid": "n"}]}, False),
        ),
        (
            "save_employees",
            {"save_employees": {"n": "6"}},
            lambda s: s.save_employees(d, {"new": [{"uid": "n"}]}),
        ),
        (
            "save_pay_classes unchanged",
            {},
            lambda s: s.save_pay_classes(d, {"new": []}),
        ),
        (
            "save_takeoffs_condition",
            {},
            lambda s: s.save_takeoffs_condition(d, ["30"], "11"),
        ),
        (
            "save_takeoffs_condition without refresh",
            {},
            lambda s: s.save_takeoffs_condition(d, ["30", "32"], "11", False),
        ),
        (
            "duplicate_conditions_to_bid into the active bid",
            {("duplicate_conditions", "execute_to_bid"): {"c1": "c9"}},
            lambda s: s.duplicate_conditions_to_bid(d, "8", "7", ["c1"]),
        ),
        (
            "duplicate_conditions_to_bid without refresh",
            {("duplicate_conditions", "execute_to_bid"): {"c1": "c9"}},
            lambda s: s.duplicate_conditions_to_bid(d, "7", "8", ["c1"], False),
        ),
        (
            "duplicate_conditions_to_bid empty map",
            {("duplicate_conditions", "execute_to_bid"): {}},
            lambda s: s.duplicate_conditions_to_bid(d, "7", "8", ["c1"]),
        ),
        (
            "create_condition_result without bid",
            {"insert_condition": None},
            lambda s: s.create_condition_result(d, "", CreateConditionSpec(name="C")),
        ),
        (
            "delete_condition_folders_result without bid",
            {},
            lambda s: s.delete_condition_folders_result(d, "", ["f1"]),
        ),
        (
            "delete_condition_folders_result empty",
            {},
            lambda s: s.delete_condition_folders_result(d, "7", []),
        ),
        (
            "insert_takeoffs_result empty",
            {},
            lambda s: s.insert_takeoffs_result(d, "7", []),
        ),
        (
            "save_bid_areas_result new only",
            {"save_bid_areas": {"new_0": "9"}},
            lambda s: s.save_bid_areas_result(
                d,
                "7",
                BidAreaChangeset(
                    new=[BidArea("new_0", "7", "0", "N", 1)],
                    updated=[],
                    deleted_uids=[],
                ),
            ),
        ),
        (
            "save_bid_areas_result updated only",
            {"save_bid_areas": {}},
            lambda s: s.save_bid_areas_result(
                d,
                "7",
                BidAreaChangeset(
                    new=[], updated=[BidArea("5", "7", "0", "U", 2)], deleted_uids=[]
                ),
            ),
        ),
        (
            "duplicate_conditions_result reassign",
            {"duplicate_conditions": ["c9"]},
            lambda s: s.duplicate_conditions_result(
                d,
                "7",
                ["10"],
                reassign_takeoffs=ConditionTakeoffReassignment("10", "20", ("30",)),
            ),
        ),
    )


def _queue_rows(d="database"):
    """(label, scripted use-case results, submit(service, callback))."""
    areas = BidAreaChangeset(
        new=[BidArea(uid="new_0", bid_uid="7", parent_uid="0", name="N", sequence=1)],
        updated=[BidArea(uid="5", bid_uid="7", parent_uid="0", name="U", sequence=2)],
        deleted_uids=["6"],
    )
    return (
        (
            "queue_project_create",
            {"create_project": "9"},
            lambda s, cb: s.queue_project_create(d, "North", cb),
        ),
        (
            "queue_bid_create",
            {"create_bid": "13"},
            lambda s, cb: s.queue_bid_create(
                d,
                "3",
                {"job_name": "B", "job_status_uid": "2", "estimator_uid": "5"},
                cb,
            ),
        ),
        (
            "queue_bid_create orphan",
            {"create_bid": "13"},
            lambda s, cb: s.queue_bid_create(d, None, {"job_name": "B"}, cb),
        ),
        (
            "queue_project_rename",
            {},
            lambda s, cb: s.queue_project_rename(d, "3", "Renamed", cb),
        ),
        (
            "queue_bids_move",
            {},
            lambda s, cb: s.queue_bids_move(
                d, ["7", "", "8", "7"], "4", cb, original_project_uid="3"
            ),
        ),
        (
            "queue_bids_move to orphan",
            {},
            lambda s, cb: s.queue_bids_move(d, ["7"], None, cb),
        ),
        (
            "queue_bids_duplicate",
            {"duplicate_bid": _Seq("12", "13")},
            lambda s, cb: s.queue_bids_duplicate(d, ["7", "8"], "4", cb),
        ),
        (
            "queue_bids_delete",
            {},
            lambda s, cb: s.queue_bids_delete(d, ["7", "8"], cb),
        ),
        (
            "queue_projects_delete",
            {},
            lambda s, cb: s.queue_projects_delete(d, ["3", "4"], cb),
        ),
        (
            "queue_bid_job_status_update",
            {},
            lambda s, cb: s.queue_bid_job_status_update(d, "7", "2", cb),
        ),
        (
            "queue_bid_areas_save",
            {"save_bid_areas": {"new_0": "9"}},
            lambda s, cb: s.queue_bid_areas_save(d, "7", areas, cb),
        ),
        (
            "queue_cover_sheet_save",
            {},
            lambda s, cb: s.queue_cover_sheet_save(
                d,
                "7",
                {
                    "job_status_uid": "2",
                    "estimator_uid": "5",
                    "deleted_page_uids": ["20"],
                    "pages": [{"uid": "21"}, {"uid": None}, {"uid": "20"}],
                },
                cb,
            ),
        ),
        (
            "queue_condition_types_save",
            {"save_condition_types": {"nt": "11"}},
            lambda s, cb: s.queue_condition_types_save(
                d,
                {
                    "new": [{"uid": "nt", "name": "N"}],
                    "updated": [{"uid": "8", "name": "U"}],
                    "deleted_uids": ["9", "", "9"],
                },
                cb,
            ),
        ),
        (
            "queue_default_layer_insert",
            {("insert_layer", "execute_default"): "42"},
            lambda s, cb: s.queue_default_layer_insert(d, "Default", 1, cb),
        ),
        (
            "queue_default_layers_delete",
            {},
            lambda s, cb: s.queue_default_layers_delete(d, ["40", "", "41", "40"], cb),
        ),
        (
            "queue_default_layer_update rename",
            {},
            lambda s, cb: s.queue_default_layer_update(
                d, "rename", {"layer_uid": 40, "name": "Walls"}, cb
            ),
        ),
        (
            "queue_default_layer_update show",
            {},
            lambda s, cb: s.queue_default_layer_update(
                d, "show", {"layer_uid": "40", "show": 0}, cb
            ),
        ),
        (
            "queue_default_layer_update show_all",
            {},
            lambda s, cb: s.queue_default_layer_update(d, "show_all", {"show": 1}, cb),
        ),
        (
            "queue_default_layer_update reorder",
            {},
            lambda s, cb: s.queue_default_layer_update(
                d, "reorder", {"layer_uid": "40", "neighbor_uid": "41"}, cb
            ),
        ),
        (
            "queue_job_statuses_save",
            {"save_job_statuses": {"n": "5"}},
            lambda s, cb: s.queue_job_statuses_save(
                d,
                {
                    "new": [{"uid": "n", "name": "Open"}],
                    "updated": [{"uid": "4", "name": "Won"}],
                    "deleted_uids": ["3"],
                },
                cb,
            ),
        ),
        (
            "queue_employees_save",
            {"save_employees": {"n": "6"}},
            lambda s, cb: s.queue_employees_save(
                d, {"new": [Employee(uid="n", first_name="Ava")]}, cb
            ),
        ),
        (
            "queue_pay_classes_save",
            {"save_pay_classes": {"n": "7"}},
            lambda s, cb: s.queue_pay_classes_save(
                d, {"new": [{"uid": "n", "name": "Field"}]}, cb
            ),
        ),
        (
            "queue_pages_delete",
            {},
            lambda s, cb: s.queue_pages_delete(d, "7", ["20", "", "21", "20"], cb),
        ),
        (
            "queue_pages_delete single",
            {},
            lambda s, cb: s.queue_pages_delete(
                d, "7", ["20"], cb, owning_surface="page-dialog"
            ),
        ),
        (
            "queue_condition_create",
            {"insert_condition": "c9"},
            lambda s, cb: s.queue_condition_create(
                d,
                "7",
                CreateConditionSpec(
                    name="C", cdn_type_uid="3", layer_uid="40", folder_uid="f1"
                ),
                cb,
            ),
        ),
        (
            "queue_condition_create plain",
            {"insert_condition": "c9"},
            lambda s, cb: s.queue_condition_create(
                d, "7", CreateConditionSpec(name="C"), cb
            ),
        ),
        (
            "queue_conditions_delete",
            {},
            lambda s, cb: s.queue_conditions_delete(d, "7", ["c1", "", "c2", "c1"], cb),
        ),
        (
            "queue_conditions_duplicate",
            {
                "duplicate_conditions": ["c9", "c10"],
                "update_condition": UpdateConditionResultDto(success=True),
            },
            lambda s, cb: s.queue_conditions_duplicate(
                d,
                "7",
                ["c1", "c2"],
                cb,
                target_changes={"folder_uid": "f1", "cdn_type_uid": "3", "name": "X"},
            ),
        ),
        (
            "queue_conditions_update",
            {"update_condition": UpdateConditionResultDto(success=True)},
            lambda s, cb: s.queue_conditions_update(
                d,
                "7",
                ["c1", "c2"],
                {
                    "folder_uid": "f1",
                    "layer_uid": "40",
                    "cdn_type_uid": "3",
                    "z_value": 1.5,
                },
                cb,
            ),
        ),
        (
            "queue_conditions_update clearing type",
            {"update_condition": UpdateConditionResultDto(success=True)},
            lambda s, cb: s.queue_conditions_update(
                d, "7", ["c1"], {"cdn_type_uid": None}, cb
            ),
        ),
        (
            "queue_conditions_renumber",
            {},
            lambda s, cb: s.queue_conditions_renumber(d, "7", ["c2", "", "c1"], cb),
        ),
        (
            "queue_condition_folder_create",
            {"insert_condition_folder": "f9"},
            lambda s, cb: s.queue_condition_folder_create(d, "7", "Walls", "f1", cb),
        ),
        (
            "queue_condition_folder_create root",
            {"insert_condition_folder": "f9"},
            lambda s, cb: s.queue_condition_folder_create(d, "7", "Walls", None, cb),
        ),
        (
            "queue_condition_folder_rename",
            {},
            lambda s, cb: s.queue_condition_folder_rename(d, "7", "f1", "N", cb),
        ),
        (
            "queue_condition_folders_delete",
            {},
            lambda s, cb: s.queue_condition_folders_delete(
                d, "7", ["f1", "", "f2"], cb
            ),
        ),
        (
            "queue_layer_insert",
            {"insert_layer": "41"},
            lambda s, cb: s.queue_layer_insert(d, "7", "Layer", 2, cb),
        ),
        (
            "queue_layer_delete",
            {},
            lambda s, cb: s.queue_layer_delete(d, "7", "40", cb),
        ),
        (
            "queue_layers_delete",
            {},
            lambda s, cb: s.queue_layers_delete(d, "7", ["40", "41", "40"], cb),
        ),
        (
            "queue_layer_reorder",
            {},
            lambda s, cb: s.queue_layer_reorder(d, "7", "40", "41", cb),
        ),
        (
            "queue_all_layers_show",
            {},
            lambda s, cb: s.queue_all_layers_show(d, "7", 0, ["40", 41, "40"], cb),
        ),
        (
            "queue_layer_rename",
            {},
            lambda s, cb: s.queue_layer_rename(d, "7", "40", "Walls", cb),
        ),
        (
            "queue_project_import",
            {},
            lambda s, cb: s.queue_project_import(
                d, "9", _import_payload(), _import_work, cb
            ),
        ),
        (
            "queue_project_import orphan",
            {},
            lambda s, cb: s.queue_project_import(
                d, None, _import_payload(None), _import_work, cb
            ),
        ),
    )


def _plan_specs():
    return [
        InsertTakeoffSpec(
            condition_uid="10",
            page_uid="20",
            area_uid="5",
            parent_uid="30",
            position=[1.0, 2.0],
        ),
        InsertTakeoffSpec(
            condition_uid="11",
            page_uid="21",
            area_uid="0",
            position=[3.0, 4.0],
        ),
    ]


def _cross_bid_paste_payload():
    payload = MdbSqlBehaviorParityTests._mixed_paste_payload()
    return replace(payload, source_bid_uid="6", destination_bid_uid="7")


def _plan_local_rows(d=_Harness.DATABASE):
    """(label, scripted use-case results, command(service)) for Access plan commands."""
    pin = ResourceRef("condition", "10", 7)
    return (
        (
            "delete_local mixed",
            {},
            lambda s: s.execute_plan_items_delete_local(
                d,
                "7",
                ["30", "31"],
                [("a1", "rect"), ("a2", "line")],
                page_uids=("20", "21"),
                dependency_resources=(pin,),
            ),
        ),
        (
            "delete_local takeoffs only without refresh",
            {},
            lambda s: s.execute_plan_items_delete_local(
                d,
                "7",
                ["30"],
                [],
                page_uids=("20",),
                publish_database_refreshed_after_write=False,
            ),
        ),
        (
            "delete_local annotations only",
            {},
            lambda s: s.execute_plan_items_delete_local(d, "7", [], [("a1", "rect")]),
        ),
        (
            "geometry_local mixed",
            {},
            lambda s: s.execute_plan_geometry_local(
                d,
                "7",
                takeoff_positions=[("30", [1, 2]), ("31", [3.5, 4])],
                takeoff_rotations=[("30", 90), ("32", 45.5)],
                annotation_positions=[("a1", "rect", [1, 2, 3, 4])],
                page_uids=("20", "21"),
                dependency_resources=(pin,),
            ),
        ),
        (
            "geometry_local rotation only",
            {},
            lambda s: s.execute_plan_geometry_local(
                d, "7", takeoff_rotations=[("32", 45)], page_uids=("21",)
            ),
        ),
        (
            "geometry_local annotations only without refresh",
            {},
            lambda s: s.execute_plan_geometry_local(
                d,
                "7",
                annotation_positions=[("a1", "line", [1, 2])],
                publish_database_refreshed_after_write=False,
            ),
        ),
        (
            "properties_local takeoff_text",
            {},
            lambda s: s.execute_plan_properties_local(
                d, "7", "takeoff_text", [("30", {"Text": "T"})], page_uids=("20",)
            ),
        ),
        (
            "properties_local takeoff_area",
            {},
            lambda s: s.execute_plan_properties_local(
                d, "7", "takeoff_area", [("30", "5"), ("32", "6"), ("31", "5")]
            ),
        ),
        (
            "properties_local takeoff_condition",
            {},
            lambda s: s.execute_plan_properties_local(
                d, "7", "takeoff_condition", [("30", "10"), ("32", "10")]
            ),
        ),
        (
            "properties_local takeoff_negative",
            {},
            lambda s: s.execute_plan_properties_local(
                d, "7", "takeoff_negative", [("30", True), ("32", False), ("31", 1)]
            ),
        ),
        (
            "properties_local takeoff_curve",
            {},
            lambda s: s.execute_plan_properties_local(
                d, "7", "takeoff_curve", [("30", [1, 2], 3)]
            ),
        ),
        (
            "properties_local annotation_text",
            {},
            lambda s: s.execute_plan_properties_local(
                d, "7", "annotation_text", [("a1", "rect", {"Text": "T"})]
            ),
        ),
        (
            "properties_local annotation_style without refresh",
            {},
            lambda s: s.execute_plan_properties_local(
                d,
                "7",
                "annotation_style",
                [("a1", "rect", {"color": "#112233"})],
                publish_database_refreshed_after_write=False,
            ),
        ),
        (
            "paste_local same bid",
            {
                "insert_takeoffs": _Seq(["p-new"], ["h-new"]),
                "insert_annotations": _Seq(["named-new"], ["rect-new"]),
            },
            lambda s: s.execute_plan_items_paste_local(
                d, MdbSqlBehaviorParityTests._mixed_paste_payload()
            ),
        ),
        (
            "paste_local cross bid",
            {
                "insert_takeoffs": _Seq(["p-new"], ["h-new"]),
                "insert_annotations": _Seq(["named-new"], ["rect-new"]),
                ("duplicate_conditions", "execute_to_bid"): {"c1": "c9"},
            },
            lambda s: s.execute_plan_items_paste_local(d, _cross_bid_paste_payload()),
        ),
    )


def _plan_queue_rows(d=_Harness.DATABASE):
    """(label, scripted use-case results, submit(service, callback), harness setup)."""
    pin = ResourceRef("condition", "10", 7)
    guard = lambda harness: setattr(harness.tokens, "guard", True)
    return (
        (
            "placement",
            {"insert_takeoffs": ["101", "102"]},
            lambda s, cb: s.queue_takeoff_placement(
                d, "7", _plan_specs(), "7b3c5ac1-e623-44aa-8203-26a0125873b9", cb
            ),
            None,
        ),
        (
            "delete mixed",
            {},
            lambda s, cb: s.queue_plan_items_delete(
                d,
                "7",
                ["30", "31"],
                [("a1", "rect"), ("a2", "line")],
                cb,
                page_uids=("20", "21"),
                dependency_resources=(pin,),
            ),
            None,
        ),
        (
            "delete takeoffs only",
            {},
            lambda s, cb: s.queue_plan_items_delete(
                d, "7", ["30"], [], cb, page_uids=("20",), owning_surface="page-dialog"
            ),
            None,
        ),
        (
            "delete annotations only",
            {},
            lambda s, cb: s.queue_plan_items_delete(d, "7", [], [("a1", "rect")], cb),
            None,
        ),
        (
            "geometry mixed",
            {},
            lambda s, cb: s.queue_plan_geometry(
                d,
                "7",
                cb,
                takeoff_positions=[("30", [1, 2]), ("31", [3.5, 4])],
                takeoff_rotations=[("30", 90), ("32", 45.5)],
                annotation_positions=[("a1", "rect", [1, 2, 3, 4])],
                page_uids=("20", "21"),
                dependency_resources=(pin,),
            ),
            None,
        ),
        (
            "geometry rotation only",
            {},
            lambda s, cb: s.queue_plan_geometry(
                d, "7", cb, takeoff_rotations=[("32", 45)], page_uids=("21",)
            ),
            None,
        ),
        (
            "geometry annotations only",
            {},
            lambda s, cb: s.queue_plan_geometry(
                d, "7", cb, annotation_positions=[("a1", "line", [1, 2])]
            ),
            None,
        ),
        (
            "properties takeoff_text",
            {},
            lambda s, cb: s.queue_plan_properties(
                d, "7", "takeoff_text", [("30", {"Text": "T"})], cb, page_uids=("20",)
            ),
            guard,
        ),
        (
            "properties takeoff_area",
            {},
            lambda s, cb: s.queue_plan_properties(
                d,
                "7",
                "takeoff_area",
                [("30", "5"), ("32", "0"), ("31", "5")],
                cb,
                dependency_resources=(pin,),
            ),
            guard,
        ),
        (
            "properties takeoff_condition",
            {},
            lambda s, cb: s.queue_plan_properties(
                d, "7", "takeoff_condition", [("30", "10"), ("32", "10")], cb
            ),
            guard,
        ),
        (
            "properties takeoff_negative",
            {},
            lambda s, cb: s.queue_plan_properties(
                d, "7", "takeoff_negative", [("30", True), ("32", False)], cb
            ),
            guard,
        ),
        (
            "properties takeoff_curve",
            {},
            lambda s, cb: s.queue_plan_properties(
                d, "7", "takeoff_curve", [("30", [1, 2], 3)], cb, page_uids=("20", "21")
            ),
            guard,
        ),
        (
            "properties annotation_text",
            {},
            lambda s, cb: s.queue_plan_properties(
                d, "7", "annotation_text", [("a1", "rect", {"Text": "T"})], cb
            ),
            guard,
        ),
        (
            "properties annotation_style",
            {},
            lambda s, cb: s.queue_plan_properties(
                d, "7", "annotation_style", [("a1", "rect", {"color": "#112233"})], cb
            ),
            guard,
        ),
        (
            "paste same bid",
            {
                "insert_takeoffs": _Seq(["p-new"], ["h-new"]),
                "insert_annotations": _Seq(["named-new"], ["rect-new"]),
            },
            lambda s, cb: s.queue_plan_items_paste(
                d, MdbSqlBehaviorParityTests._mixed_paste_payload(), cb
            ),
            None,
        ),
        (
            "paste cross bid",
            {
                "insert_takeoffs": _Seq(["p-new"], ["h-new"]),
                "insert_annotations": _Seq(["named-new"], ["rect-new"]),
                ("duplicate_conditions", "execute_to_bid"): {"c1": "c9"},
            },
            lambda s, cb: s.queue_plan_items_paste(
                d,
                _cross_bid_paste_payload(),
                cb,
                dependency_resources=(pin,),
                owning_surface="paste-dialog",
            ),
            None,
        ),
        (
            "page scale",
            {},
            lambda s, cb: s.queue_page_settings(
                d, "7", "scale", [["20", 1, 96.5], ["21", 1, 96.5], ["20", 1, 96.5]], cb
            ),
            None,
        ),
        (
            "page show_mode",
            {},
            lambda s, cb: s.queue_page_settings(d, "7", "show_mode", [["20", 2]], cb),
            None,
        ),
        (
            "page overlay_image",
            {},
            lambda s, cb: s.queue_page_settings(
                d, "7", "overlay_image", [["20", "C:/o.png"]], cb
            ),
            None,
        ),
        (
            "page overlay_rect",
            {},
            lambda s, cb: s.queue_page_settings(
                d, "7", "overlay_rect", [["20", [1, 2, 3, 4]]], cb
            ),
            None,
        ),
        (
            "page invert",
            {},
            lambda s, cb: s.queue_page_settings(d, "7", "invert", [["20", 1]], cb),
            None,
        ),
        (
            "page bitonal",
            {},
            lambda s, cb: s.queue_page_settings(d, "7", "bitonal", [["20", 0]], cb),
            None,
        ),
        (
            "page image_adjustments",
            {},
            lambda s, cb: s.queue_page_settings(
                d,
                "7",
                "image_adjustments",
                [["20", 90, 1, 0, 1, 0], ["21", 90, 1, 0, 1, 0]],
                cb,
            ),
            None,
        ),
        (
            "page area",
            {},
            lambda s, cb: s.queue_page_settings(d, "7", "area", [["20", "5"]], cb),
            None,
        ),
        (
            "page name",
            {},
            lambda s, cb: s.queue_page_settings(
                d, "7", "name", [["20", "Sheet"]], cb, owning_surface="rename-dialog"
            ),
            None,
        ),
        (
            "page layer_show",
            {},
            lambda s, cb: s.queue_page_settings(
                d, "7", "layer_show", [["40", 0], ["41", 1]], cb
            ),
            None,
        ),
    )


def _import_payload(target="9"):
    return ProjectImportPayload(
        source_path="C:/imports/project.ost",
        source_kind="ost",
        source_size=123,
        source_modified_ns=456,
        target_project_uid=target,
    )


def _import_work(_recorder):
    return {
        "project_uids": {"target": "9"},
        "bid_uids": {"b": "10"},
        "page_uids": {"p": "20"},
        "condition_uids": {"c": "30"},
        "layer_uids": {"l": "40"},
        "area_uids": {"r": "50"},
        "takeoff_uids": {"t": "60"},
        "annotation_uids": {"a": "70"},
    }


_NONE_ON_FAILURE = frozenset(
    {
        "create_project",
        "create_project_result",
        "create_bid",
        "create_bid_result",
        "create_bid_result orphan",
        "duplicate_bid",
        "duplicate_bid_result",
        "duplicate_bid_result without reload",
        "create_condition_folder_result",
        "create_condition_result",
        "duplicate_conditions",
        "duplicate_conditions_result",
        "insert_layer",
        "insert_layer_result",
        "insert_default_layer_result",
        "save_job_statuses",
        "save_employees",
        "save_employees_result",
        "save_employees_result without refresh",
        "save_pay_classes",
        "save_condition_types",
        "save_condition_types_result",
        "save_condition_types_result without refresh",
        "save_condition_types_result partially blocked",
        "delete_condition_types_result",
        "save_bid_areas",
        "save_bid_areas_result",
        "save_bid_areas_result without refresh",
        "save_bid_areas_result deletion only",
    }
)
_SCENARIOS = (
    "failure",
    "denied",
    "locked",
    "conflict",
    "unknown",
    "reload_failed",
    "other_database",
    "equivalent_path",
)
_PLAN_SCENARIOS = tuple(name for name in _SCENARIOS if name != "locked")
_ALTERNATE_DATABASES = {
    "other_database": "C:/jobs/other.mdb",
    "equivalent_path": "c:\\JOBS\\Test.MDB",
}


def _failure_value(use_case, method, label=""):
    if label in _NONE_ON_FAILURE:
        return None
    if label == "duplicate_conditions_to_bid":
        return {}
    if (use_case, method) == ("duplicate_conditions", "execute_to_bid"):
        return {}
    if use_case in {"insert_takeoffs", "insert_annotations"}:
        return []
    return False


def _synchronization_conflict():
    return SynchronizationConflict(
        "C:/jobs/test.mdb",
        ResourceRef("takeoff", "1", 7),
        "stale",
        kind=SynchronizationConflictKind.OPTIMISTIC_CONCURRENCY,
    )


def _outcome_text(result):
    if isinstance(result, MutationExecutionResult):
        return (
            f"outcome={result.outcome_status.value} message={result.message!r}"
            f" commit={result.commit_attempted} tokens={result.consumed_lock_tokens!r}"
            f" conflict={'yes' if result.conflict else 'no'}"
            f" authoritative={'yes' if result.authoritative_result else 'no'}"
            f" created={result.created_resource_ids!r}"
        )
    return repr(result)


def _scenario_text(harness, result):
    events = [event.__name__ for event, _payload in harness.events.published]
    requests = [
        ",".join(harness.resource_text(r) for r in request.resources)
        for request in harness.executor.requests
    ]
    return (
        f"{_outcome_text(result)} | calls={len(harness.calls)} requests={requests!r}"
        f" records={len(harness.executor.recorder.changes)}"
        f" values={harness.executor.values!r}"
        f" verify={len(harness.executor.verifications)}"
        f" reloads={len(harness.reloads)} events={events!r}"
    )


def _apply_status(harness, scenario):
    if scenario == "conflict":
        harness.executor.status = MutationOutcomeStatus.CONFLICT
        harness.executor.conflict = _synchronization_conflict()
    elif scenario == "unknown":
        harness.executor.status = MutationOutcomeStatus.COMMIT_STATUS_UNKNOWN
        harness.executor.commit_attempted = True
        harness.executor.consumed_lock_tokens = ("lease-1",)


def _local_scenario_text(rows, label, scenario, sql=False):
    database = _ALTERNATE_DATABASES.get(scenario, _Harness.DATABASE)
    results, command = next(
        (row[1], row[2]) for row in rows(database) if row[0] == label
    )
    kwargs = {}
    if scenario == "denied":
        kwargs["editable"] = False
    if scenario == "reload_failed":
        kwargs["reload_result"] = False
    if scenario == "failure":
        probe = _Harness(results, sql=sql)
        command(probe.service)
        if not probe.calls:
            return "no use case is reached"
        use_case, method = probe.calls[0][0], probe.calls[0][1]
        results = {
            **results,
            (use_case, method): _failure_value(use_case, method, label),
        }
    harness = _Harness(results, sql=sql, **kwargs)
    if scenario == "locked":
        harness.data.locked = True
    _apply_status(harness, scenario)
    try:
        result = command(harness.service)
    except Exception as exc:
        result = f"raised {type(exc).__name__}: {exc}"
    return _scenario_text(harness, result)


def _queue_scenario_text(rows, label, scenario):
    row = next(row for row in rows() if row[0] == label)
    results, submit = row[1], row[2]
    setup = row[3] if len(row) > 3 else None
    harness = _Harness(results, editable=scenario != "denied")
    if setup:
        setup(harness)
    submit(harness.service, lambda _result: None)
    _request, execute, _callback = harness.provider.requests[-1]
    _apply_status(harness, scenario)
    try:
        result = execute()
    except Exception as exc:
        result = f"raised {type(exc).__name__}: {exc}"
    return _scenario_text(harness, result)


_LOCAL_EXPECTED = {
    "delete_bids": (
        "result=True\n"
        "call delete_bids.execute('C:/jobs/test.mdb', ['7', '8'])\n"
        "request bid:7@7,bid:8@8 child=True editors=True type=project_write\n"
        "value True\n"
        "record bid:7@7 delete\n"
        "record bid:8@8 delete\n"
        "reload C:/jobs/test.mdb\n"
        "event REFRESH\n"
    ),
    "delete_bids without refresh": (
        "result=True\n"
        "call delete_bids.execute('C:/jobs/test.mdb', ['7'])\n"
        "request bid:7@7 child=True editors=True type=project_write\n"
        "value True\n"
        "record bid:7@7 delete\n"
    ),
    "delete_bids empty": ("result=True\n"),
    "delete_projects": (
        "result=True\n"
        "call delete_projects.execute('C:/jobs/test.mdb', ['3', '4'])\n"
        "request project:3@None,project:4@None,bid:31@31,bid:41@41,projects_collection:database@None child=True editors=True type=project_write\n"
        "value True\n"
        "record bid:31@31 move fields=['project_uid']\n"
        "record bid:41@41 move fields=['project_uid']\n"
        "record project:3@None delete\n"
        "record project:4@None delete\n"
        "record projects_collection:database@None update\n"
        "reload C:/jobs/test.mdb\n"
        "event REFRESH\n"
    ),
    "create_project_result": (
        "result=WriteReloadResult(value='9', write_success=True, reload_success=True, failure_reason=None, blocked_uids=[])\n"
        "call create_project.execute('C:/jobs/test.mdb', 'North')\n"
        "request projects_collection:database@None child=False editors=False type=project_write\n"
        "value '9'\n"
        "record project:9@None create fields=['name']\n"
        "record projects_collection:database@None update\n"
        "reload C:/jobs/test.mdb\n"
        "event REFRESH\n"
    ),
    "rename_project": (
        "result=True\n"
        "call rename_project.execute('C:/jobs/test.mdb', '3', 'Renamed')\n"
        "request project:3@None child=False editors=False type=project_write\n"
        "value True\n"
        "record project:3@None update fields=['name']\n"
        "reload C:/jobs/test.mdb\n"
        "event REFRESH\n"
    ),
    "move_bids": (
        "result=True\n"
        "call move_bids.execute('C:/jobs/test.mdb', ['7', '8'], '4', '3')\n"
        "request bid:7@7,bid:8@8,project_bids:3@None,project_bids:4@None child=False editors=False type=project_write\n"
        "value True\n"
        "record bid:7@7 move fields=['project_uid']\n"
        "record bid:8@8 move fields=['project_uid']\n"
        "record project_bids:3@None move fields=['project_uid']\n"
        "record project_bids:4@None move fields=['project_uid']\n"
        "reload C:/jobs/test.mdb\n"
        "event REFRESH\n"
    ),
    "move_bids to orphan": (
        "result=True\n"
        "call move_bids.execute('C:/jobs/test.mdb', ['7'], None, None)\n"
        "request bid:7@7,project_bids:orphan@None child=False editors=False type=project_write\n"
        "value True\n"
        "record bid:7@7 move fields=['project_uid']\n"
        "record project_bids:orphan@None move fields=['project_uid']\n"
    ),
    "duplicate_bid_result": (
        "result=WriteReloadResult(value='12', write_success=True, reload_success=True, failure_reason=None, blocked_uids=[])\n"
        "call duplicate_bid.execute('C:/jobs/test.mdb', '7')\n"
        "request bid:7@7 child=True editors=False type=project_write\n"
        "value '12'\n"
        "record bid:12@None create\n"
        "reload C:/jobs/test.mdb\n"
        "event REFRESH\n"
    ),
    "duplicate_bid_result without reload": (
        "result=WriteReloadResult(value='12', write_success=True, reload_success=True, failure_reason=None, blocked_uids=[])\n"
        "call duplicate_bid.execute('C:/jobs/test.mdb', '7')\n"
        "request bid:7@7 child=True editors=False type=project_write\n"
        "value '12'\n"
        "record bid:12@None create\n"
    ),
    "create_bid_result": (
        "result=WriteReloadResult(value='13', write_success=True, reload_success=True, failure_reason=None, blocked_uids=[])\n"
        "call create_bid.execute('C:/jobs/test.mdb', '3', {'job_name': 'B'})\n"
        "request project_bids:3@None child=False editors=False type=project_write\n"
        "value '13'\n"
        "record bid:13@None create\n"
        "record project_bids:3@None update\n"
        "reload C:/jobs/test.mdb\n"
        "event REFRESH\n"
    ),
    "create_bid_result orphan": (
        "result=WriteReloadResult(value='13', write_success=True, reload_success=True, failure_reason=None, blocked_uids=[])\n"
        "call create_bid.execute('C:/jobs/test.mdb', None, {})\n"
        "request project_bids:orphan@None child=False editors=False type=project_write\n"
        "value '13'\n"
        "record bid:13@None create\n"
        "record project_bids:orphan@None update\n"
        "reload C:/jobs/test.mdb\n"
        "event REFRESH\n"
    ),
    "delete_conditions": (
        "result=True\n"
        "call delete_conditions.execute('C:/jobs/test.mdb', '7', ['c1', 'c2'])\n"
        "request conditions_collection:7@7 child=False editors=False type=project_write\n"
        "value True\n"
        "record condition:c1@7 delete\n"
        "record condition:c2@7 delete\n"
        "record conditions_collection:7@7 update\n"
        "reload C:/jobs/test.mdb\n"
        "event ConditionsChangedEvent {'database_id': 'C:/jobs/test.mdb', 'bid_uid': '7', 'condition_uids': ['c1', 'c2'], 'changed_fields': [], 'change_operations': ['delete'], 'invalidates_undo': True, 'local_completion': True}\n"
    ),
    "create_condition_folder_result": (
        "result=WriteReloadResult(value='f9', write_success=True, reload_success=True, failure_reason=None, blocked_uids=[])\n"
        "call insert_condition_folder.execute('C:/jobs/test.mdb', '7', 'Walls', 'f1')\n"
        "request conditions_collection:7@7 child=False editors=False type=project_write\n"
        "value 'f9'\n"
        "record condition_folder:f9@7 create\n"
        "record conditions_collection:7@7 update\n"
        "reload C:/jobs/test.mdb\n"
        "event DatabaseRefreshedEvent {'file_path': 'C:/jobs/test.mdb', 'external_change': True}\n"
    ),
    "rename_condition_folder": (
        "result=True\n"
        "call rename_condition_folder.execute('C:/jobs/test.mdb', 'f1', 'N')\n"
        "request condition_folder:f1@7 child=False editors=False type=project_write\n"
        "value True\n"
        "record condition_folder:f1@7 update\n"
        "reload C:/jobs/test.mdb\n"
        "event DatabaseRefreshedEvent {'file_path': 'C:/jobs/test.mdb', 'external_change': True}\n"
    ),
    "duplicate_conditions_result": (
        "result=WriteReloadResult(value=['c9', 'c10'], write_success=True, reload_success=True, failure_reason=None, blocked_uids=[])\n"
        "call duplicate_conditions.execute('C:/jobs/test.mdb', '7', ['c1', 'c2'])\n"
        "request conditions_collection:7@7 child=False editors=False type=project_write\n"
        "value ('c9', 'c10')\n"
        "record condition:c10@7 create\n"
        "record condition:c9@7 create\n"
        "record conditions_collection:7@7 update\n"
        "reload C:/jobs/test.mdb\n"
        "event ConditionsChangedEvent {'database_id': 'C:/jobs/test.mdb', 'bid_uid': '7', 'condition_uids': ['c9', 'c10'], 'changed_fields': [], 'change_operations': ['create'], 'invalidates_undo': False, 'local_completion': True}\n"
    ),
    "duplicate_conditions_to_bid": (
        "result={'c1': 'c9', 'c2': 'c10'}\n"
        "call duplicate_conditions.execute_to_bid('C:/jobs/test.mdb', '7', '8', ['c1', 'c2'])\n"
        "request conditions_collection:8@8 child=False editors=False type=project_write\n"
        "value {'c1': 'c9', 'c2': 'c10'}\n"
        "record condition:c10@8 create\n"
        "record condition:c9@8 create\n"
        "record conditions_collection:8@8 update\n"
        "reload C:/jobs/test.mdb\n"
        "event ConditionsChangedEvent {'database_id': 'C:/jobs/test.mdb', 'bid_uid': '8', 'condition_uids': ['c9', 'c10'], 'changed_fields': [], 'change_operations': ['create'], 'invalidates_undo': False, 'local_completion': True}\n"
    ),
    "renumber_conditions": (
        "result=True\n"
        "call renumber_conditions.execute('C:/jobs/test.mdb', '7', ['c2', 'c1'])\n"
        "request conditions_collection:7@7 child=False editors=False type=project_write\n"
        "value True\n"
        "record conditions_collection:7@7 reorder\n"
        "reload C:/jobs/test.mdb\n"
        "event DatabaseRefreshedEvent {'file_path': 'C:/jobs/test.mdb', 'external_change': True}\n"
    ),
    "set_takeoff_curve": (
        "result=True\n"
        "call set_takeoff_curve.execute('C:/jobs/test.mdb', '30', [1.0, 2.0], 3)\n"
        "request takeoff:30@7 child=False editors=False type=project_write\n"
        "value True\n"
        "record takeoff:30@7 update fields=['position', 'curve']\n"
        "reload C:/jobs/test.mdb\n"
        "event REFRESH\n"
    ),
    "save_takeoff_positions": (
        "result=True\n"
        "call save_takeoff_positions.execute('C:/jobs/test.mdb', [('30', [1.0, 2.0]), ('31', [3.0, 4.0])])\n"
        "request takeoff:30@7,takeoff:31@7 child=False editors=False type=project_write\n"
        "value True\n"
        "record takeoff:30@7 update fields=['position']\n"
        "record takeoff:31@7 update fields=['position']\n"
        "reload C:/jobs/test.mdb\n"
        "event REFRESH\n"
    ),
    "save_takeoff_rotations": (
        "result=True\n"
        "call save_takeoff_rotations.execute('C:/jobs/test.mdb', [('30', 90.0)])\n"
        "request takeoff:30@7 child=False editors=False type=project_write\n"
        "value True\n"
        "record takeoff:30@7 update fields=['rotation']\n"
        "reload C:/jobs/test.mdb\n"
        "event REFRESH\n"
    ),
    "save_takeoff_text_properties": (
        "result=True\n"
        "call save_takeoff_text_properties.execute('C:/jobs/test.mdb', [('30', {'Text': 'T'})])\n"
        "request takeoff:30@7 child=False editors=False type=project_write\n"
        "value True\n"
        "record takeoff:30@7 update fields=['text_properties']\n"
        "reload C:/jobs/test.mdb\n"
        "event REFRESH\n"
    ),
    "save_takeoffs_area": (
        "result=True\n"
        "call save_takeoffs_area.execute('C:/jobs/test.mdb', ['30', '31'], '5')\n"
        "request takeoff:30@7,takeoff:31@7 child=False editors=False type=project_write\n"
        "value True\n"
        "record takeoff:30@7 update fields=['assignment']\n"
        "record takeoff:31@7 update fields=['assignment']\n"
        "reload C:/jobs/test.mdb\n"
        "event REFRESH\n"
    ),
    "set_takeoffs_negative": (
        "result=True\n"
        "call set_takeoffs_negative.execute('C:/jobs/test.mdb', ['30', '31'], True)\n"
        "request takeoff:30@7,takeoff:31@7 child=False editors=False type=project_write\n"
        "value True\n"
        "record takeoff:30@7 update fields=['negative']\n"
        "record takeoff:31@7 update fields=['negative']\n"
        "reload C:/jobs/test.mdb\n"
        "event REFRESH\n"
    ),
    "delete_takeoffs": (
        "result=True\n"
        "call delete_takeoffs.execute('C:/jobs/test.mdb', ['30', '31'])\n"
        "request takeoff:30@7,takeoff:31@7 child=False editors=False type=project_write\n"
        "value True\n"
        "record takeoff:30@7 delete\n"
        "record takeoff:31@7 delete\n"
        "reload C:/jobs/test.mdb\n"
        "event REFRESH\n"
    ),
    "save_page_scale": (
        "result=True\n"
        "call save_page_scale.execute('C:/jobs/test.mdb', '20', 1.0, 96.0)\n"
        "request page:20@7 child=False editors=False type=project_write\n"
        "value True\n"
        "record page:20@7 update fields=['scale']\n"
        "reload C:/jobs/test.mdb\n"
        "event DatabaseRefreshedEvent {'file_path': 'C:/jobs/test.mdb', 'image_sources_unchanged': True, 'mesh_scene_unchanged': False, 'page_scale_uids': ('20',)}\n"
    ),
    "save_page_name": (
        "result=True\n"
        "call save_page_name.execute('C:/jobs/test.mdb', '20', 'Sheet')\n"
        "request page:20@7 child=False editors=False type=project_write\n"
        "value True\n"
        "record page:20@7 update fields=['name']\n"
        "reload C:/jobs/test.mdb\n"
        "event DatabaseRefreshedEvent {'file_path': 'C:/jobs/test.mdb', 'image_sources_unchanged': True, 'mesh_scene_unchanged': True, 'page_scale_uids': ()}\n"
    ),
    "save_page_scales": (
        "result=True\n"
        "call save_page_scale.execute('C:/jobs/test.mdb', '20', 1.0, 96.0)\n"
        "call save_page_scale.execute('C:/jobs/test.mdb', '21', 1.0, 96.0)\n"
        "request page:20@7,page:21@7 child=False editors=False type=project_write\n"
        "value (True, True)\n"
        "record page:20@7 update fields=['scale']\n"
        "record page:21@7 update fields=['scale']\n"
        "reload C:/jobs/test.mdb\n"
        "event DatabaseRefreshedEvent {'file_path': 'C:/jobs/test.mdb', 'image_sources_unchanged': True, 'mesh_scene_unchanged': False, 'page_scale_uids': ('20', '21')}\n"
    ),
    "save_page_show_mode": (
        "result=True\n"
        "call save_page_show_mode.execute('C:/jobs/test.mdb', '20', 2)\n"
        "request page:20@7 child=False editors=False type=project_write\n"
        "value True\n"
        "record page:20@7 update fields=['show_mode']\n"
        "reload C:/jobs/test.mdb\n"
        "event REFRESH\n"
    ),
    "save_page_show_mode without refresh": (
        "result=True\n"
        "call save_page_show_mode.execute('C:/jobs/test.mdb', '20', 2)\n"
        "request page:20@7 child=False editors=False type=project_write\n"
        "value True\n"
        "record page:20@7 update fields=['show_mode']\n"
    ),
    "save_page_overlay_image": (
        "result=True\n"
        "call save_page_overlay_image.execute('C:/jobs/test.mdb', '20', 'C:/o.png')\n"
        "request page:20@7 child=False editors=False type=project_write\n"
        "value True\n"
        "record page:20@7 update fields=['overlay_image']\n"
        "reload C:/jobs/test.mdb\n"
        "event REFRESH\n"
    ),
    "save_page_overlay_rect_result": (
        "result=WriteReloadResult(value=None, write_success=True, reload_success=True, failure_reason=None, blocked_uids=[])\n"
        "call save_page_overlay_rect.execute('C:/jobs/test.mdb', '20', (1.0, 2.0, 3.0, 4.0))\n"
        "request page:20@7 child=False editors=False type=project_write\n"
        "value True\n"
        "record page:20@7 update fields=['overlay_rect']\n"
        "reload C:/jobs/test.mdb\n"
        "event DatabaseRefreshedEvent {'file_path': 'C:/jobs/test.mdb', 'image_sources_unchanged': True, 'mesh_scene_unchanged': False, 'page_scale_uids': ()}\n"
    ),
    "save_page_overlay_rect_result without refresh": (
        "result=WriteReloadResult(value=None, write_success=True, reload_success=True, failure_reason=None, blocked_uids=[])\n"
        "call save_page_overlay_rect.execute('C:/jobs/test.mdb', '20', (1.0, 2.0, 3.0, 4.0))\n"
        "request page:20@7 child=False editors=False type=project_write\n"
        "value True\n"
        "record page:20@7 update fields=['overlay_rect']\n"
    ),
    "save_page_invert": (
        "result=True\n"
        "call save_page_invert.execute('C:/jobs/test.mdb', '20', True)\n"
        "request page:20@7 child=False editors=False type=project_write\n"
        "value True\n"
        "record page:20@7 update fields=['invert']\n"
    ),
    "save_page_bitonal": (
        "result=True\n"
        "call save_page_bitonal.execute('C:/jobs/test.mdb', '20', True)\n"
        "request page:20@7 child=False editors=False type=project_write\n"
        "value True\n"
        "record page:20@7 update fields=['bitonal']\n"
    ),
    "save_page_image_adjustments": (
        "result=True\n"
        "call save_page_image_adjustments.execute('C:/jobs/test.mdb', ['20', '21'], 90, True, False, True, False)\n"
        "request page:20@7,page:21@7 child=False editors=False type=project_write\n"
        "value True\n"
        "record page:20@7 update fields=['image_adjustments']\n"
        "record page:21@7 update fields=['image_adjustments']\n"
        "reload C:/jobs/test.mdb\n"
        "event REFRESH\n"
    ),
    "save_page_area": (
        "result=True\n"
        "call save_page_area.execute('C:/jobs/test.mdb', '20', '5')\n"
        "request page:20@7 child=False editors=False type=project_write\n"
        "value True\n"
        "record page:20@7 update fields=['area']\n"
        "reload C:/jobs/test.mdb\n"
        "event REFRESH\n"
    ),
    "update_layer_show": (
        "result=True\n"
        "call update_layer_show.execute('C:/jobs/test.mdb', '40', False)\n"
        "request layer:40@7 child=False editors=False type=project_write\n"
        "value True\n"
        "record layer:40@7 update fields=['show']\n"
        "reload C:/jobs/test.mdb\n"
        "event REFRESH\n"
    ),
    "insert_layer_result": (
        "result=WriteReloadResult(value='41', write_success=True, reload_success=True, failure_reason=None, blocked_uids=[])\n"
        "call insert_layer.execute('C:/jobs/test.mdb', '7', 'Layer', 2)\n"
        "request layers_collection:7@7 child=False editors=False type=project_write\n"
        "value '41'\n"
        "record layer:41@7 create\n"
        "record layers_collection:7@7 update\n"
        "reload C:/jobs/test.mdb\n"
        "event REFRESH\n"
    ),
    "insert_default_layer_result": (
        "result=WriteReloadResult(value='42', write_success=True, reload_success=True, failure_reason=None, blocked_uids=[])\n"
        "call insert_layer.execute_default('C:/jobs/test.mdb', 'Default', 1)\n"
        "request default_layers_collection:database@None child=False editors=False type=project_write\n"
        "value '42'\n"
        "record default_layers_collection:database@None update\n"
        "reload C:/jobs/test.mdb\n"
        "event REFRESH\n"
    ),
    "delete_layer": (
        "result=True\n"
        "call delete_layer.execute('C:/jobs/test.mdb', '40')\n"
        "request layer:40@7 child=False editors=False type=project_write\n"
        "value True\n"
        "record layer:40@7 delete\n"
        "reload C:/jobs/test.mdb\n"
        "event REFRESH\n"
    ),
    "delete_layers": (
        "result=BatchWriteResult(requested_uids=['40', '41'], succeeded_uids=['40', '41'], failed_uids=[], reload_success=True)\n"
        "call delete_layer.execute('C:/jobs/test.mdb', '40')\n"
        "call delete_layer.execute('C:/jobs/test.mdb', '41')\n"
        "request layer:40@7,layer:41@7 child=False editors=False type=project_write\n"
        "value True\n"
        "record layer:40@7 delete\n"
        "record layer:41@7 delete\n"
        "reload C:/jobs/test.mdb\n"
        "event REFRESH\n"
    ),
    "delete_default_layers": (
        "result=BatchWriteResult(requested_uids=['40', '41'], succeeded_uids=['40', '41'], failed_uids=[], reload_success=True)\n"
        "call delete_layer.execute_default('C:/jobs/test.mdb', '40')\n"
        "call delete_layer.execute_default('C:/jobs/test.mdb', '41')\n"
        "request default_layers_collection:database@None child=False editors=False type=project_write\n"
        "value True\n"
        "record default_layers_collection:database@None update\n"
        "reload C:/jobs/test.mdb\n"
        "event REFRESH\n"
    ),
    "update_all_layers_show": (
        "result=True\n"
        "call update_all_layers_show.execute('C:/jobs/test.mdb', '7', False, ['40', '41'])\n"
        "request layers_collection:7@7 child=False editors=False type=project_write\n"
        "value True\n"
        "record layers_collection:7@7 update fields=['show']\n"
        "reload C:/jobs/test.mdb\n"
        "event REFRESH\n"
    ),
    "update_all_default_layers_show": (
        "result=True\n"
        "call update_all_layers_show.execute_default('C:/jobs/test.mdb', True)\n"
        "request default_layers_collection:database@None child=False editors=False type=project_write\n"
        "value True\n"
        "record default_layers_collection:database@None update fields=['show']\n"
        "reload C:/jobs/test.mdb\n"
        "event REFRESH\n"
    ),
    "swap_layer_sequence": (
        "result=True\n"
        "call swap_layer_sequence.execute('C:/jobs/test.mdb', '40', '41')\n"
        "request layers_collection:7@7 child=False editors=False type=project_write\n"
        "value True\n"
        "record layers_collection:7@7 reorder\n"
        "reload C:/jobs/test.mdb\n"
        "event REFRESH\n"
    ),
    "swap_default_layer_sequence": (
        "result=True\n"
        "call swap_layer_sequence.execute_default('C:/jobs/test.mdb', '40', '41')\n"
        "request default_layers_collection:database@None child=False editors=False type=project_write\n"
        "value True\n"
        "record default_layers_collection:database@None reorder\n"
        "reload C:/jobs/test.mdb\n"
        "event REFRESH\n"
    ),
    "update_layer_name": (
        "result=True\n"
        "call update_layer_name.execute('C:/jobs/test.mdb', '40', 'Walls')\n"
        "request layer:40@7 child=False editors=False type=project_write\n"
        "value True\n"
        "record layer:40@7 update fields=['name']\n"
        "reload C:/jobs/test.mdb\n"
        "event REFRESH\n"
    ),
    "update_default_layer_name": (
        "result=True\n"
        "call update_layer_name.execute_default('C:/jobs/test.mdb', '40', 'Walls')\n"
        "request default_layers_collection:database@None child=False editors=False type=project_write\n"
        "value True\n"
        "record default_layers_collection:database@None update fields=['name']\n"
        "reload C:/jobs/test.mdb\n"
        "event REFRESH\n"
    ),
    "update_default_layer_show": (
        "result=True\n"
        "call update_layer_show.execute_default('C:/jobs/test.mdb', '40', False)\n"
        "request default_layers_collection:database@None child=False editors=False type=project_write\n"
        "value True\n"
        "record default_layers_collection:database@None update fields=['show']\n"
        "reload C:/jobs/test.mdb\n"
        "event REFRESH\n"
    ),
    "save_page_view_state": (
        "result=True\n"
        "call save_page_view_state.execute('C:/jobs/test.mdb', '20', 2.0, 3.0, 4.0)\n"
    ),
    "save_bid_selected_page": (
        "result=True\n"
        "call save_bid_selected_page.execute('C:/jobs/test.mdb', '7', '20')\n"
    ),
    "save_cover_sheet": (
        "result=True\n"
        "call save_cover_sheet.execute('C:/jobs/test.mdb', '7', {'job_name': 'N', 'bid_no': '2'})\n"
        "request cover_sheet:7@7 child=False editors=False type=project_write\n"
        "value True\n"
        "record cover_sheet:7@7 update fields=['bid_no', 'job_name']\n"
        "reload C:/jobs/test.mdb\n"
        "event REFRESH\n"
    ),
    "delete_pages": (
        "result=True\n"
        "call delete_pages.execute('C:/jobs/test.mdb', ['20', '21'])\n"
        "request page:20@7,page:21@7 child=False editors=False type=project_write\n"
        "value True\n"
        "record page:20@7 delete\n"
        "record page:21@7 delete\n"
        "reload C:/jobs/test.mdb\n"
        "event REFRESH\n"
    ),
    "update_bid_job_status": (
        "result=True\n"
        "call update_bid_job_status.execute('C:/jobs/test.mdb', '7', '2')\n"
        "request bid:7@7 child=False editors=False type=project_write\n"
        "value True\n"
        "record bid:7@7 update fields=['job_status']\n"
        "reload C:/jobs/test.mdb\n"
        "event REFRESH\n"
    ),
    "save_job_statuses": (
        "result={'n': '5'}\n"
        "call save_job_statuses.execute('C:/jobs/test.mdb', {'new': [{'uid': 'n'}]})\n"
        "request job_statuses_collection:database@None child=False editors=False type=project_write\n"
        "value {'n': '5'}\n"
        "record job_statuses_collection:database@None update\n"
        "reload C:/jobs/test.mdb\n"
        "event REFRESH\n"
    ),
    "save_employees_result": (
        "result=WriteReloadResult(value={'n': '6'}, write_success=True, reload_success=True, failure_reason=None, blocked_uids=[])\n"
        "call save_employees.execute('C:/jobs/test.mdb', {'new': [{'uid': 'n'}]})\n"
        "request employees_collection:database@None child=False editors=False type=project_write\n"
        "value {'n': '6'}\n"
        "record employees_collection:database@None update\n"
        "reload C:/jobs/test.mdb\n"
        "event REFRESH\n"
    ),
    "save_pay_classes": (
        "result={'n': '7'}\n"
        "call save_pay_classes.execute('C:/jobs/test.mdb', {'deleted_uids': ['9']})\n"
        "request pay_classes_collection:database@None child=False editors=False type=project_write\n"
        "value {'n': '7'}\n"
        "record pay_classes_collection:database@None update\n"
        "reload C:/jobs/test.mdb\n"
        "event REFRESH\n"
    ),
    "save_job_statuses unchanged": ("result={}\n"),
    "create_project": (
        "result='9'\n"
        "call create_project.execute('C:/jobs/test.mdb', 'North')\n"
        "request projects_collection:database@None child=False editors=False type=project_write\n"
        "value '9'\n"
        "record project:9@None create fields=['name']\n"
        "record projects_collection:database@None update\n"
        "reload C:/jobs/test.mdb\n"
        "event REFRESH\n"
    ),
    "create_bid": (
        "result='13'\n"
        "call create_bid.execute('C:/jobs/test.mdb', '3', {'job_name': 'B'})\n"
        "request project_bids:3@None child=False editors=False type=project_write\n"
        "value '13'\n"
        "record bid:13@None create\n"
        "record project_bids:3@None update\n"
        "reload C:/jobs/test.mdb\n"
        "event REFRESH\n"
    ),
    "duplicate_bid": (
        "result='12'\n"
        "call duplicate_bid.execute('C:/jobs/test.mdb', '7')\n"
        "request bid:7@7 child=True editors=False type=project_write\n"
        "value '12'\n"
        "record bid:12@None create\n"
        "reload C:/jobs/test.mdb\n"
        "event REFRESH\n"
    ),
    "insert_layer": (
        "result='41'\n"
        "call insert_layer.execute('C:/jobs/test.mdb', '7', 'Layer', 2)\n"
        "request layers_collection:7@7 child=False editors=False type=project_write\n"
        "value '41'\n"
        "record layer:41@7 create\n"
        "record layers_collection:7@7 update\n"
        "reload C:/jobs/test.mdb\n"
        "event REFRESH\n"
    ),
    "duplicate_conditions": (
        "result=['c9', 'c10']\n"
        "call duplicate_conditions.execute('C:/jobs/test.mdb', '7', ['c1', 'c2'])\n"
        "request conditions_collection:7@7 child=False editors=False type=project_write\n"
        "value ('c9', 'c10')\n"
        "record condition:c10@7 create\n"
        "record condition:c9@7 create\n"
        "record conditions_collection:7@7 update\n"
        "reload C:/jobs/test.mdb\n"
        "event ConditionsChangedEvent {'database_id': 'C:/jobs/test.mdb', 'bid_uid': '7', 'condition_uids': ['c9', 'c10'], 'changed_fields': [], 'change_operations': ['create'], 'invalidates_undo': False, 'local_completion': True}\n"
    ),
    "insert_takeoffs": (
        "result=['101', '102']\n"
        "call insert_takeoffs.execute('C:/jobs/test.mdb', '7', [InsertTakeoffSpec(condition_uid='10', page_uid='20', area_uid='5', position=[1.0, 2.0], parent_uid='30', curve=-1, rotation=0.0, is_negative=False, raw_extras={}, source_bid_uid=None), InsertTakeoffSpec(condition_uid='11', page_uid='21', area_uid='0', position=[3.0, 4.0], parent_uid=None, curve=-1, rotation=0.0, is_negative=False, raw_extras={}, source_bid_uid=None)])\n"
        "request takeoffs_collection:7@7 child=False editors=False type=takeoff_placement\n"
        "value ['101', '102']\n"
        "record takeoff:101@7 create\n"
        "record takeoff:102@7 create\n"
        "record takeoffs_collection:7@7 update\n"
        "reload C:/jobs/test.mdb\n"
        "event REFRESH\n"
    ),
    "insert_takeoffs_result without refresh": (
        "result=WriteReloadResult(value=['101', '102'], write_success=True, reload_success=True, failure_reason=None, blocked_uids=[])\n"
        "call insert_takeoffs.execute('C:/jobs/test.mdb', '7', [InsertTakeoffSpec(condition_uid='10', page_uid='20', area_uid='5', position=[1.0, 2.0], parent_uid='30', curve=-1, rotation=0.0, is_negative=False, raw_extras={}, source_bid_uid=None), InsertTakeoffSpec(condition_uid='11', page_uid='21', area_uid='0', position=[3.0, 4.0], parent_uid=None, curve=-1, rotation=0.0, is_negative=False, raw_extras={}, source_bid_uid=None)])\n"
        "request takeoffs_collection:7@7 child=False editors=False type=takeoff_placement\n"
        "value ['101', '102']\n"
        "record takeoff:101@7 create\n"
        "record takeoff:102@7 create\n"
        "record takeoffs_collection:7@7 update\n"
    ),
    "insert_takeoffs_result consistency": (
        "result=WriteReloadResult(value=['101', '102'], write_success=True, reload_success=True, failure_reason=None, blocked_uids=[])\n"
        "call insert_takeoffs.execute('C:/jobs/test.mdb', '7', [InsertTakeoffSpec(condition_uid='10', page_uid='20', area_uid='5', position=[1.0, 2.0], parent_uid='30', curve=-1, rotation=0.0, is_negative=False, raw_extras={}, source_bid_uid=None), InsertTakeoffSpec(condition_uid='11', page_uid='21', area_uid='0', position=[3.0, 4.0], parent_uid=None, curve=-1, rotation=0.0, is_negative=False, raw_extras={}, source_bid_uid=None)])\n"
        "request condition:10@7,page:21@7,takeoffs_collection:7@7 child=False editors=False type=takeoff_placement\n"
        "value ['101', '102']\n"
        "record takeoff:101@7 create\n"
        "record takeoff:102@7 create\n"
        "record takeoffs_collection:7@7 update\n"
        "reload C:/jobs/test.mdb\n"
        "event REFRESH\n"
    ),
    "insert_takeoffs empty": ("result=[]\n"),
    "delete_projects empty": ("result=True\n"),
    "move_bids empty": ("result=True\n"),
    "delete_conditions empty": ("result=True\n"),
    "delete_conditions without bid": (
        "result=True\n"
        "call delete_conditions.execute('C:/jobs/test.mdb', '', ['c1'])\n"
        "request conditions_collection:unknown@None child=False editors=False type=project_write\n"
        "value True\n"
        "record condition:c1@None delete\n"
        "record conditions_collection:unknown@None update\n"
        "reload C:/jobs/test.mdb\n"
        "event ConditionsChangedEvent {'database_id': 'C:/jobs/test.mdb', 'bid_uid': '', 'condition_uids': ['c1'], 'changed_fields': [], 'change_operations': ['delete'], 'invalidates_undo': True, 'local_completion': True}\n"
    ),
    "renumber_conditions empty": ("result=True\n"),
    "save_takeoff_positions empty": ("result=False\n"),
    "save_takeoff_rotations empty": ("result=False\n"),
    "save_takeoff_text_properties empty": ("result=False\n"),
    "save_takeoffs_area empty": ("result=False\n"),
    "set_takeoffs_negative empty": ("result=False\n"),
    "delete_takeoffs empty": ("result=False\n"),
    "save_takeoffs_condition empty": ("result=False\n"),
    "save_page_scales empty": ("result=False\n"),
    "save_page_image_adjustments empty": ("result=False\n"),
    "delete_pages empty": ("result=False\n"),
    "delete_layers empty": (
        "result=BatchWriteResult(requested_uids=[], succeeded_uids=[], failed_uids=[], reload_success=False)\n"
    ),
    "delete_default_layers empty": (
        "result=BatchWriteResult(requested_uids=[], succeeded_uids=[], failed_uids=[], reload_success=False)\n"
    ),
    "update_all_layers_show without layer uids": (
        "result=True\n"
        "call update_all_layers_show.execute('C:/jobs/test.mdb', '7', True, None)\n"
        "request layers_collection:7@7 child=False editors=False type=project_write\n"
        "value True\n"
        "record layers_collection:7@7 update fields=['show']\n"
        "reload C:/jobs/test.mdb\n"
        "event REFRESH\n"
    ),
    "update_condition": (
        "result=UpdateConditionResultDto(success=True, error=None, error_presented=False)\n"
        "call update_condition.execute('C:/jobs/test.mdb', '7', 'c1', UpdateConditionDto{'name': 'Renamed', 'z_value': 2.0})\n"
        "request condition:c1@7 child=False editors=False type=project_write\n"
        "value UpdateConditionResultDto(success=True, error=None, error_presented=False)\n"
        "record condition:c1@7 update fields=['name', 'z_value']\n"
        "reload C:/jobs/test.mdb\n"
        "event DatabaseRefreshedEvent {'file_path': 'C:/jobs/test.mdb', 'external_change': True}\n"
    ),
    "create_condition_result": (
        "result=CreateConditionResult(value='c9', write_success=True, reload_success=True, failure_reason=None, blocked_uids=[], projection=None)\n"
        "call insert_condition.execute('C:/jobs/test.mdb', '7', CreateConditionSpec(name='C', condition_type=0, backout=False, cdn_type_uid=None, layer_uid=None, height=0.0, width=12.0, depth=0.0, thickness=4.0, rise=0.0, run=0.0, display_size=100.0, shape=-1, pattern=0, spacing=4.0, color_fill=0, uom1=0, uom2=-1, uom3=-1, calc_type1=0, calc_type2=0, calc_type3=0, notes='', drop_run=False, drop_value=0.0, round_quantity=False, round_up=0.0, trim=False, is_curved_segment=False, grid=False, grid_size1=0.0, grid_size2=0.0, gap=0.0, display_dimension=False, display_name=False, display_grid_while_drawing=False, folder_uid='f1'))\n"
        "request conditions_collection:7@7 child=False editors=False type=project_write\n"
        "value 'c9'\n"
        "record condition:c9@7 create\n"
        "record conditions_collection:7@7 update\n"
        "reload C:/jobs/test.mdb\n"
        "event ConditionsChangedEvent {'database_id': 'C:/jobs/test.mdb', 'bid_uid': '7', 'condition_uids': ['c9'], 'changed_fields': [], 'change_operations': ['create'], 'invalidates_undo': False, 'local_completion': True}\n"
    ),
    "delete_condition_folders_result": (
        "result=WriteReloadResult(value=['f1', 'f2'], write_success=True, reload_success=True, failure_reason=None, blocked_uids=[])\n"
        "call delete_condition_folders.execute('C:/jobs/test.mdb', ['f1', 'f2'])\n"
        "request conditions_collection:7@7 child=False editors=False type=project_write\n"
        "value True\n"
        "record condition_folder:f1@7 delete\n"
        "record condition_folder:f2@7 delete\n"
        "record conditions_collection:7@7 update\n"
        "reload C:/jobs/test.mdb\n"
        "event DatabaseRefreshedEvent {'file_path': 'C:/jobs/test.mdb', 'external_change': True}\n"
    ),
    "delete_condition_folders": (
        "result=True\n"
        "call delete_condition_folders.execute('C:/jobs/test.mdb', ['f1'])\n"
        "request conditions_collection:7@7 child=False editors=False type=project_write\n"
        "value True\n"
        "record condition_folder:f1@7 delete\n"
        "record conditions_collection:7@7 update\n"
        "reload C:/jobs/test.mdb\n"
        "event DatabaseRefreshedEvent {'file_path': 'C:/jobs/test.mdb', 'external_change': True}\n"
    ),
    "save_condition_types_result": (
        "result=WriteReloadResult(value={'n': '11'}, write_success=True, reload_success=True, failure_reason=None, blocked_uids=[])\n"
        "call save_condition_types.execute('C:/jobs/test.mdb', {'new': [{'uid': 'n', 'name': 'N'}], 'updated': [], 'deleted_uids': ['9', '8']})\n"
        "request condition_types_collection:database@None child=False editors=False type=project_write\n"
        "value {'n': '11'}\n"
        "record condition_types_collection:database@None update\n"
        "reload C:/jobs/test.mdb\n"
        "event ConditionsChangedEvent {'database_id': 'C:/jobs/test.mdb', 'bid_uid': '7', 'condition_uids': [], 'changed_fields': ['condition_type_catalog'], 'change_operations': [], 'invalidates_undo': False, 'local_completion': True}\n"
    ),
    "save_condition_types_result partially blocked": (
        "result=WriteReloadResult(value={}, write_success=True, reload_success=True, failure_reason='condition_type_in_use', blocked_uids=['used'])\n"
        "call save_condition_types.execute('C:/jobs/test.mdb', {'new': [], 'updated': [], 'deleted_uids': ['9']})\n"
        "request condition_types_collection:database@None child=False editors=False type=project_write\n"
        "value {}\n"
        "record condition_types_collection:database@None update\n"
        "reload C:/jobs/test.mdb\n"
        "event ConditionsChangedEvent {'database_id': 'C:/jobs/test.mdb', 'bid_uid': '7', 'condition_uids': [], 'changed_fields': ['condition_type_catalog'], 'change_operations': [], 'invalidates_undo': False, 'local_completion': True}\n"
    ),
    "save_condition_types_result blocked": (
        "result=WriteReloadResult(value=None, write_success=False, reload_success=False, failure_reason='condition_type_in_use', blocked_uids=['used'])\n"
    ),
    "save_condition_types_result without refresh": (
        "result=WriteReloadResult(value={'n': '11'}, write_success=True, reload_success=True, failure_reason=None, blocked_uids=[])\n"
        "call save_condition_types.execute('C:/jobs/test.mdb', {'new': [{'uid': 'n', 'name': 'N'}], 'deleted_uids': []})\n"
        "request condition_types_collection:database@None child=False editors=False type=project_write\n"
        "value {'n': '11'}\n"
        "record condition_types_collection:database@None update\n"
    ),
    "save_condition_types_result empty": (
        "result=WriteReloadResult(value={}, write_success=True, reload_success=True, failure_reason=None, blocked_uids=[])\n"
    ),
    "save_condition_types": (
        "result={'n': '11'}\n"
        "call save_condition_types.execute('C:/jobs/test.mdb', {'new': [{'uid': 'n', 'name': 'N'}], 'deleted_uids': []})\n"
        "request condition_types_collection:database@None child=False editors=False type=project_write\n"
        "value {'n': '11'}\n"
        "record condition_types_collection:database@None update\n"
        "reload C:/jobs/test.mdb\n"
        "event ConditionsChangedEvent {'database_id': 'C:/jobs/test.mdb', 'bid_uid': '7', 'condition_uids': [], 'changed_fields': ['condition_type_catalog'], 'change_operations': [], 'invalidates_undo': False, 'local_completion': True}\n"
    ),
    "delete_condition_types_result": (
        "result=WriteReloadResult(value={}, write_success=True, reload_success=True, failure_reason=None, blocked_uids=[])\n"
        "call save_condition_types.execute('C:/jobs/test.mdb', {'new': [], 'updated': [], 'deleted_uids': ['9']})\n"
        "request condition_types_collection:database@None child=False editors=False type=project_write\n"
        "value {}\n"
        "record condition_types_collection:database@None update\n"
        "reload C:/jobs/test.mdb\n"
        "event ConditionsChangedEvent {'database_id': 'C:/jobs/test.mdb', 'bid_uid': '7', 'condition_uids': [], 'changed_fields': ['condition_type_catalog'], 'change_operations': [], 'invalidates_undo': False, 'local_completion': True}\n"
    ),
    "save_bid_areas_result": (
        "result=WriteReloadResult(value={'new_0': '9'}, write_success=True, reload_success=True, failure_reason=None, blocked_uids=[])\n"
        "call save_bid_areas.execute('C:/jobs/test.mdb', '7', BidAreaChangeset(new=[BidArea(uid='new_0', bid_uid='7', parent_uid='0', name='N', sequence=1, guid='')], updated=[BidArea(uid='5', bid_uid='7', parent_uid='0', name='U', sequence=2, guid='')], deleted_uids=['6']))\n"
        "request areas_collection:7@7 child=False editors=False type=project_write\n"
        "value {'new_0': '9'}\n"
        "record area:5@7 update\n"
        "record area:6@7 delete\n"
        "record area:9@7 create\n"
        "record areas_collection:7@7 update\n"
        "reload C:/jobs/test.mdb\n"
        "event BidAreasDeletedEvent {'database_id': 'C:/jobs/test.mdb', 'bid_uid': '7', 'area_uids': ('6',)}\n"
        "event REFRESH\n"
    ),
    "save_bid_areas_result without refresh": (
        "result=WriteReloadResult(value={'new_0': '9'}, write_success=True, reload_success=True, failure_reason=None, blocked_uids=[])\n"
        "call save_bid_areas.execute('C:/jobs/test.mdb', '7', BidAreaChangeset(new=[BidArea(uid='new_0', bid_uid='7', parent_uid='0', name='N', sequence=1, guid='')], updated=[BidArea(uid='5', bid_uid='7', parent_uid='0', name='U', sequence=2, guid='')], deleted_uids=['6']))\n"
        "request areas_collection:7@7 child=False editors=False type=project_write\n"
        "value {'new_0': '9'}\n"
        "record area:5@7 update\n"
        "record area:6@7 delete\n"
        "record area:9@7 create\n"
        "record areas_collection:7@7 update\n"
        "event BidAreasDeletedEvent {'database_id': 'C:/jobs/test.mdb', 'bid_uid': '7', 'area_uids': ('6',)}\n"
    ),
    "save_bid_areas_result deletion only": (
        "result=WriteReloadResult(value={}, write_success=True, reload_success=True, failure_reason=None, blocked_uids=[])\n"
        "call save_bid_areas.execute('C:/jobs/test.mdb', '7', BidAreaChangeset(new=[], updated=[], deleted_uids=['6']))\n"
        "request areas_collection:7@7 child=False editors=False type=project_write\n"
        "value {}\n"
        "record area:6@7 delete\n"
        "record areas_collection:7@7 update\n"
        "reload C:/jobs/test.mdb\n"
        "event BidAreasDeletedEvent {'database_id': 'C:/jobs/test.mdb', 'bid_uid': '7', 'area_uids': ('6',)}\n"
        "event REFRESH\n"
    ),
    "save_bid_areas_result unchanged": (
        "result=WriteReloadResult(value={}, write_success=True, reload_success=True, failure_reason=None, blocked_uids=[])\n"
        "call save_bid_areas.execute('C:/jobs/test.mdb', '7', BidAreaChangeset(new=[], updated=[], deleted_uids=[]))\n"
        "request areas_collection:7@7 child=False editors=False type=project_write\n"
        "value {}\n"
    ),
    "save_bid_areas": (
        "result={'new_0': '9'}\n"
        "call save_bid_areas.execute('C:/jobs/test.mdb', '7', BidAreaChangeset(new=[BidArea(uid='new_0', bid_uid='7', parent_uid='0', name='N', sequence=1, guid='')], updated=[BidArea(uid='5', bid_uid='7', parent_uid='0', name='U', sequence=2, guid='')], deleted_uids=['6']))\n"
        "request areas_collection:7@7 child=False editors=False type=project_write\n"
        "value {'new_0': '9'}\n"
        "record area:5@7 update\n"
        "record area:6@7 delete\n"
        "record area:9@7 create\n"
        "record areas_collection:7@7 update\n"
        "reload C:/jobs/test.mdb\n"
        "event BidAreasDeletedEvent {'database_id': 'C:/jobs/test.mdb', 'bid_uid': '7', 'area_uids': ('6',)}\n"
        "event REFRESH\n"
    ),
    "save_employees_result empty": (
        "result=WriteReloadResult(value={}, write_success=True, reload_success=True, failure_reason=None, blocked_uids=[])\n"
    ),
    "save_employees_result without refresh": (
        "result=WriteReloadResult(value={'n': '6'}, write_success=True, reload_success=True, failure_reason=None, blocked_uids=[])\n"
        "call save_employees.execute('C:/jobs/test.mdb', {'new': [{'uid': 'n'}]})\n"
        "request employees_collection:database@None child=False editors=False type=project_write\n"
        "value {'n': '6'}\n"
        "record employees_collection:database@None update\n"
    ),
    "save_employees": (
        "result=True\n"
        "call save_employees.execute('C:/jobs/test.mdb', {'new': [{'uid': 'n'}]})\n"
        "request employees_collection:database@None child=False editors=False type=project_write\n"
        "value {'n': '6'}\n"
        "record employees_collection:database@None update\n"
        "reload C:/jobs/test.mdb\n"
        "event REFRESH\n"
    ),
    "save_pay_classes unchanged": ("result={}\n"),
    "save_takeoffs_condition": (
        "result=True\n"
        "call save_takeoffs_condition.execute('C:/jobs/test.mdb', ['30'], '11')\n"
        "request takeoff:30@7 child=False editors=False type=project_write\n"
        "value True\n"
        "record takeoff:30@7 update fields=['condition']\n"
        "reload C:/jobs/test.mdb\n"
        "event REFRESH\n"
    ),
    "save_takeoffs_condition without refresh": (
        "result=True\n"
        "call save_takeoffs_condition.execute('C:/jobs/test.mdb', ['30', '32'], '11')\n"
        "request takeoff:30@7,takeoff:32@7 child=False editors=False type=project_write\n"
        "value True\n"
        "record takeoff:30@7 update fields=['condition']\n"
        "record takeoff:32@7 update fields=['condition']\n"
    ),
    "duplicate_conditions_to_bid into the active bid": (
        "result={'c1': 'c9'}\n"
        "call duplicate_conditions.execute_to_bid('C:/jobs/test.mdb', '8', '7', ['c1'])\n"
        "request conditions_collection:7@7 child=False editors=False type=project_write\n"
        "value {'c1': 'c9'}\n"
        "record condition:c9@7 create\n"
        "record conditions_collection:7@7 update\n"
        "reload C:/jobs/test.mdb\n"
        "event ConditionsChangedEvent {'database_id': 'C:/jobs/test.mdb', 'bid_uid': '7', 'condition_uids': ['c9'], 'changed_fields': [], 'change_operations': ['create'], 'invalidates_undo': False, 'local_completion': True}\n"
    ),
    "duplicate_conditions_to_bid without refresh": (
        "result={'c1': 'c9'}\n"
        "call duplicate_conditions.execute_to_bid('C:/jobs/test.mdb', '7', '8', ['c1'])\n"
        "request conditions_collection:8@8 child=False editors=False type=project_write\n"
        "value {'c1': 'c9'}\n"
        "record condition:c9@8 create\n"
        "record conditions_collection:8@8 update\n"
    ),
    "duplicate_conditions_to_bid empty map": (
        "result={}\n"
        "call duplicate_conditions.execute_to_bid('C:/jobs/test.mdb', '7', '8', ['c1'])\n"
        "request conditions_collection:8@8 child=False editors=False type=project_write\n"
        "value {}\n"
    ),
    "create_condition_result without bid": (
        "result=CreateConditionResult(value=None, write_success=False, reload_success=False, failure_reason=None, blocked_uids=[], projection=None)\n"
        "call insert_condition.execute('C:/jobs/test.mdb', '', CreateConditionSpec(name='C', condition_type=0, backout=False, cdn_type_uid=None, layer_uid=None, height=0.0, width=12.0, depth=0.0, thickness=4.0, rise=0.0, run=0.0, display_size=100.0, shape=-1, pattern=0, spacing=4.0, color_fill=0, uom1=0, uom2=-1, uom3=-1, calc_type1=0, calc_type2=0, calc_type3=0, notes='', drop_run=False, drop_value=0.0, round_quantity=False, round_up=0.0, trim=False, is_curved_segment=False, grid=False, grid_size1=0.0, grid_size2=0.0, gap=0.0, display_dimension=False, display_name=False, display_grid_while_drawing=False, folder_uid=None))\n"
        "request conditions_collection:unknown@None child=False editors=False type=project_write\n"
        "value None\n"
    ),
    "delete_condition_folders_result without bid": (
        "result=WriteReloadResult(value=['f1'], write_success=True, reload_success=True, failure_reason=None, blocked_uids=[])\n"
        "call delete_condition_folders.execute('C:/jobs/test.mdb', ['f1'])\n"
        "request conditions_collection:unknown@None child=False editors=False type=project_write\n"
        "value True\n"
        "record condition_folder:f1@None delete\n"
        "record conditions_collection:unknown@None update\n"
        "reload C:/jobs/test.mdb\n"
        "event ConditionsChangedEvent {'database_id': 'C:/jobs/test.mdb', 'bid_uid': '', 'condition_uids': [], 'changed_fields': ['condition_folder'], 'change_operations': [], 'invalidates_undo': False, 'local_completion': True}\n"
    ),
    "delete_condition_folders_result empty": (
        "result=WriteReloadResult(value=[], write_success=True, reload_success=True, failure_reason=None, blocked_uids=[])\n"
    ),
    "insert_takeoffs_result empty": (
        "result=WriteReloadResult(value=[], write_success=True, reload_success=True, failure_reason=None, blocked_uids=[])\n"
    ),
    "save_bid_areas_result new only": (
        "result=WriteReloadResult(value={'new_0': '9'}, write_success=True, reload_success=True, failure_reason=None, blocked_uids=[])\n"
        "call save_bid_areas.execute('C:/jobs/test.mdb', '7', BidAreaChangeset(new=[BidArea(uid='new_0', bid_uid='7', parent_uid='0', name='N', sequence=1, guid='')], updated=[], deleted_uids=[]))\n"
        "request areas_collection:7@7 child=False editors=False type=project_write\n"
        "value {'new_0': '9'}\n"
        "record area:9@7 create\n"
        "record areas_collection:7@7 update\n"
        "reload C:/jobs/test.mdb\n"
        "event REFRESH\n"
    ),
    "save_bid_areas_result updated only": (
        "result=WriteReloadResult(value={}, write_success=True, reload_success=True, failure_reason=None, blocked_uids=[])\n"
        "call save_bid_areas.execute('C:/jobs/test.mdb', '7', BidAreaChangeset(new=[], updated=[BidArea(uid='5', bid_uid='7', parent_uid='0', name='U', sequence=2, guid='')], deleted_uids=[]))\n"
        "request areas_collection:7@7 child=False editors=False type=project_write\n"
        "value {}\n"
        "record area:5@7 update\n"
        "record areas_collection:7@7 update\n"
        "reload C:/jobs/test.mdb\n"
        "event REFRESH\n"
    ),
    "duplicate_conditions_result reassign": (
        "result=WriteReloadResult(value=['c9'], write_success=True, reload_success=True, failure_reason=None, blocked_uids=[])\n"
        "call duplicate_conditions.execute('C:/jobs/test.mdb', '7', ['10'])\n"
        "call save_takeoffs_condition.execute('C:/jobs/test.mdb', ['30'], 'c9')\n"
        "request condition:10@7,conditions_collection:7@7,page:20@7,takeoff:30@7,takeoff:31@7 child=False editors=False type=project_write\n"
        "verify ('C:/jobs/test.mdb', '7', ('30', '31'), (), ('30', '31'))\n"
        "reassign ('C:/jobs/test.mdb', '7', ('10', '20', ('30',)))\n"
        "value ('c9',)\n"
        "record condition:c9@7 create\n"
        "record conditions_collection:7@7 update\n"
        "record takeoff:30@7 update fields=['condition']\n"
        "reload C:/jobs/test.mdb\n"
        "event ConditionsChangedEvent {'database_id': 'C:/jobs/test.mdb', 'bid_uid': '7', 'condition_uids': ['c9'], 'changed_fields': [], 'change_operations': ['create'], 'invalidates_undo': False, 'local_completion': True}\n"
    ),
}
_QUEUE_EXPECTED = {
    "queue_project_create": (
        "request project_write surface=project-tree bid=None page=''\n"
        "resources projects_collection:database@None\n"
        "dependencies \n"
        'payload create_project {"name":"North"}\n'
        "lease=False\n"
        "outcome committed\n"
        "executed projects_collection:database@None child=False editors=False type=project_write id_ok=True hash_ok=True\n"
        "call create_project.execute('database', 'North')\n"
        "value '9'\n"
        "record project:9@None create fields=['name']\n"
        "record projects_collection:database@None update\n"
        "created=('9',) maps=(('projects', (('0', '9'),)),)\n"
        "updated  deleted \n"
        "pages=() conditions=() families=('hierarchy',)\n"
    ),
    "queue_bid_create": (
        "request project_write surface=new-project-dialog bid=None page=''\n"
        "resources project_bids:3@None\n"
        "dependencies default_layers_collection:database@None,employee:5@None,job_status:2@None,project:3@None\n"
        'payload create_bid {"project_uid":"3","updates":{"estimator_uid":"5","job_name":"B","job_status_uid":"2"}}\n'
        "lease=False\n"
        "outcome committed\n"
        "executed default_layers_collection:database@None,employee:5@None,job_status:2@None,project:3@None,project_bids:3@None child=False editors=False type=project_write id_ok=True hash_ok=True\n"
        "call create_bid.execute('database', '3', {'job_name': 'B', 'job_status_uid': '2', 'estimator_uid': '5'})\n"
        "value '13'\n"
        "record bid:13@13 create\n"
        "record project_bids:3@None update\n"
        "created=('13',) maps=(('bids', (('0', '13'),)),)\n"
        "updated  deleted \n"
        "pages=() conditions=() families=('hierarchy',)\n"
    ),
    "queue_bid_create orphan": (
        "request project_write surface=new-project-dialog bid=None page=''\n"
        "resources project_bids:orphan@None\n"
        "dependencies default_layers_collection:database@None\n"
        'payload create_bid {"project_uid":null,"updates":{"job_name":"B"}}\n'
        "lease=False\n"
        "outcome committed\n"
        "executed default_layers_collection:database@None,project_bids:orphan@None child=False editors=False type=project_write id_ok=True hash_ok=True\n"
        "call create_bid.execute('database', None, {'job_name': 'B'})\n"
        "value '13'\n"
        "record bid:13@13 create\n"
        "record project_bids:orphan@None update\n"
        "created=('13',) maps=(('bids', (('0', '13'),)),)\n"
        "updated  deleted \n"
        "pages=() conditions=() families=('hierarchy',)\n"
    ),
    "queue_project_rename": (
        "request project_write surface=project-tree bid=None page=''\n"
        "resources project:3@None\n"
        "dependencies \n"
        'payload rename_project {"name":"Renamed","project_uid":"3"}\n'
        "lease=False\n"
        "outcome committed\n"
        "executed project:3@None child=False editors=False type=project_write id_ok=True hash_ok=True\n"
        "call rename_project.execute('database', '3', 'Renamed')\n"
        "value True\n"
        "record project:3@None update fields=['name']\n"
        "created=() maps=()\n"
        "updated project:3@None deleted \n"
        "pages=() conditions=() families=('hierarchy',)\n"
    ),
    "queue_bids_move": (
        "request project_write surface=project-tree bid=7 page=''\n"
        "resources bid:7@7,bid:8@8\n"
        "dependencies project_bids:3@None,project_bids:4@None\n"
        'payload move_bids {"bid_uids":["7","8"],"original_project_uid":"3","target_project_uid":"4"}\n'
        "lease=False\n"
        "outcome committed\n"
        "executed bid:7@7,bid:8@8,project_bids:3@None,project_bids:4@None child=False editors=False type=project_write id_ok=True hash_ok=True\n"
        "call move_bids.execute('database', ['7', '8'], '4', '3')\n"
        "value True\n"
        "record bid:7@7 move fields=['project_uid']\n"
        "record bid:8@8 move fields=['project_uid']\n"
        "record project_bids:3@None update\n"
        "record project_bids:4@None update\n"
        "created=() maps=()\n"
        "updated bid:7@7,bid:8@8 deleted \n"
        "pages=() conditions=() families=('hierarchy',)\n"
    ),
    "queue_bids_move to orphan": (
        "request project_write surface=project-tree bid=7 page=''\n"
        "resources bid:7@7\n"
        "dependencies project_bids:orphan@None\n"
        'payload move_bids {"bid_uids":["7"],"original_project_uid":null,"target_project_uid":null}\n'
        "lease=False\n"
        "outcome committed\n"
        "executed bid:7@7,project_bids:orphan@None child=False editors=False type=project_write id_ok=True hash_ok=True\n"
        "call move_bids.execute('database', ['7'], None, None)\n"
        "value True\n"
        "record bid:7@7 move fields=['project_uid']\n"
        "record project_bids:orphan@None update\n"
        "created=() maps=()\n"
        "updated bid:7@7 deleted \n"
        "pages=() conditions=() families=('hierarchy',)\n"
    ),
    "queue_bids_duplicate": (
        "request project_write surface=project-tree bid=7 page=''\n"
        "resources bid:7@7,bid:8@8\n"
        "dependencies project_bids:4@None\n"
        'payload duplicate_bids {"bid_uids":["7","8"],"target_project_uid":"4"}\n'
        "lease=False\n"
        "outcome committed\n"
        "executed bid:7@7,bid:8@8,project_bids:4@None child=True editors=False type=project_write id_ok=True hash_ok=True\n"
        "call duplicate_bid.execute('database', '7')\n"
        "call duplicate_bid.execute('database', '8')\n"
        "call move_bids.execute('database', ['12', '13'], '4', None)\n"
        "value ('12', '13')\n"
        "record bid:12@12 create\n"
        "record bid:13@13 create\n"
        "record project_bids:4@None update\n"
        "created=('12', '13') maps=(('bids', (('7', '12'), ('8', '13'))),)\n"
        "updated  deleted \n"
        "pages=() conditions=() families=('hierarchy',)\n"
    ),
    "queue_bids_delete": (
        "request project_write surface=project-tree bid=7 page=''\n"
        "resources bid:7@7,bid:8@8\n"
        "dependencies projects_collection:database@None\n"
        'payload delete_bids {"bid_uids":["7","8"]}\n'
        "lease=False\n"
        "outcome committed\n"
        "executed bid:7@7,bid:8@8,projects_collection:database@None child=True editors=True type=project_write id_ok=True hash_ok=True\n"
        "call delete_bids.execute('database', ['7', '8'])\n"
        "value True\n"
        "record bid:7@7 delete\n"
        "record bid:8@8 delete\n"
        "record projects_collection:database@None update\n"
        "created=() maps=()\n"
        "updated  deleted bid:7@7,bid:8@8\n"
        "pages=() conditions=() families=('hierarchy',)\n"
    ),
    "queue_projects_delete": (
        "request project_write surface=project-tree bid=None page=''\n"
        "resources bid:31@31,bid:41@41,project:3@None,project:4@None\n"
        "dependencies projects_collection:database@None\n"
        'payload delete_projects {"project_uids":["3","4"]}\n'
        "lease=False\n"
        "outcome committed\n"
        "executed bid:31@31,bid:41@41,project:3@None,project:4@None,projects_collection:database@None child=True editors=True type=project_write id_ok=True hash_ok=True\n"
        "call delete_projects.execute('database', ['3', '4'])\n"
        "value True\n"
        "record bid:31@31 move fields=['project_uid']\n"
        "record bid:41@41 move fields=['project_uid']\n"
        "record project:3@None delete\n"
        "record project:4@None delete\n"
        "record projects_collection:database@None update\n"
        "created=() maps=()\n"
        "updated bid:31@31,bid:41@41 deleted project:3@None,project:4@None\n"
        "pages=() conditions=() families=('hierarchy',)\n"
    ),
    "queue_bid_job_status_update": (
        "request project_write surface=project-tree bid=7 page=''\n"
        "resources bid:7@7\n"
        "dependencies \n"
        'payload update_bid_job_status {"bid_uid":"7","job_status_uid":"2"}\n'
        "lease=False\n"
        "outcome committed\n"
        "executed bid:7@7 child=False editors=False type=project_write id_ok=True hash_ok=True\n"
        "call update_bid_job_status.execute('database', '7', '2')\n"
        "value True\n"
        "record bid:7@7 update fields=['job_status_uid']\n"
        "created=() maps=()\n"
        "updated bid:7@7 deleted \n"
        "pages=() conditions=() families=('hierarchy',)\n"
    ),
    "queue_bid_areas_save": (
        "request project_write surface=bid-areas-dialog bid=7 page=''\n"
        "resources area:5@7,area:6@7\n"
        "dependencies areas_collection:7@7\n"
        'payload save_bid_areas {"deleted_uids":["6"],"new":[{"bid_uid":"7","guid":"","name":"N","parent_uid":"0","sequence":1,"uid":"new_0"}],"updated":[{"bid_uid":"7","guid":"","name":"U","parent_uid":"0","sequence":2,"uid":"5"}]}\n'
        "lease=False\n"
        "outcome committed\n"
        "executed area:5@7,area:6@7,areas_collection:7@7 child=False editors=False type=project_write id_ok=True hash_ok=True\n"
        "call save_bid_areas.execute('database', '7', BidAreaChangeset(new=[BidArea(uid='new_0', bid_uid='7', parent_uid='0', name='N', sequence=1, guid='')], updated=[BidArea(uid='5', bid_uid='7', parent_uid='0', name='U', sequence=2, guid='')], deleted_uids=['6']))\n"
        "value {'uid_map': {'new_0': '9'}, 'created_resources': (ResourceRef(resource_type='area', resource_id='9', bid_uid=7),)}\n"
        "record area:5@7 update\n"
        "record area:6@7 delete\n"
        "record area:9@7 create\n"
        "record areas_collection:7@7 update\n"
        "created=('9',) maps=(('areas', (('new_0', '9'),)),)\n"
        "updated area:5@7 deleted area:6@7\n"
        "pages=() conditions=() families=('areas',)\n"
    ),
    "queue_cover_sheet_save": (
        "request project_write surface=cover-sheet-dialog bid=7 page=''\n"
        "resources cover_sheet:7@7\n"
        "dependencies annotations_collection:7@7,bid:7@7,conditions_collection:7@7,employee:5@None,job_status:2@None,pages_collection:7@7,takeoffs_collection:7@7\n"
        'payload save_cover_sheet {"deleted_page_uids":["20"],"estimator_uid":"5","job_status_uid":"2","pages":[{"uid":"21"},{"uid":null},{"uid":"20"}]}\n'
        "lease=False\n"
        "outcome committed\n"
        "executed annotations_collection:7@7,bid:7@7,conditions_collection:7@7,cover_sheet:7@7,employee:5@None,job_status:2@None,pages_collection:7@7,takeoffs_collection:7@7 child=False editors=False type=project_write id_ok=True hash_ok=True\n"
        "call save_cover_sheet.execute('database', '7', {'job_status_uid': '2', 'estimator_uid': '5', 'deleted_page_uids': ['20'], 'pages': [{'uid': '21'}, {'uid': None}, {'uid': '20'}]})\n"
        "value True\n"
        "record annotations_collection:7@7 update\n"
        "record bid:7@7 update\n"
        "record conditions_collection:7@7 update\n"
        "record cover_sheet:7@7 update\n"
        "record pages_collection:7@7 update\n"
        "record takeoffs_collection:7@7 update\n"
        "created=() maps=()\n"
        "updated cover_sheet:7@7,bid:7@7,pages_collection:7@7,conditions_collection:7@7,takeoffs_collection:7@7,annotations_collection:7@7 deleted \n"
        "pages=('20', '21') conditions=() families=('hierarchy', 'pages', 'conditions', 'takeoffs', 'annotations')\n"
    ),
    "queue_condition_types_save": (
        "request project_write surface=condition-types-dialog bid=None page=''\n"
        "resources condition_type:8@None,condition_type:9@None\n"
        "dependencies condition_types_collection:database@None\n"
        'payload save_condition_types {"deleted_uids":["9"],"new":[{"name":"N","uid":"nt"}],"updated":[{"name":"U","uid":"8"}]}\n'
        "lease=False\n"
        "outcome committed\n"
        "executed condition_type:8@None,condition_type:9@None,condition_types_collection:database@None child=False editors=False type=project_write id_ok=True hash_ok=True\n"
        "call save_condition_types.execute('database', {'new': [{'uid': 'nt', 'name': 'N'}], 'updated': [{'uid': '8', 'name': 'U'}], 'deleted_uids': ['9']})\n"
        "value {'uid_map': {'nt': '11'}, 'created_resources': (ResourceRef(resource_type='condition_type', resource_id='11', bid_uid=None),)}\n"
        "record condition_type:11@None create\n"
        "record condition_type:8@None update\n"
        "record condition_type:9@None delete\n"
        "record condition_types_collection:database@None update\n"
        "created=('11',) maps=(('condition_types', (('nt', '11'),)),)\n"
        "updated condition_type:8@None deleted condition_type:9@None\n"
        "pages=() conditions=() families=('hierarchy',)\n"
    ),
    "queue_default_layer_insert": (
        "request project_write surface=default-layers-dialog bid=None page=''\n"
        "resources default_layers_collection:database@None\n"
        "dependencies \n"
        'payload save_default_layers {"after_sequence":1,"name":"Default","operation":"insert"}\n'
        "lease=False\n"
        "outcome committed\n"
        "executed default_layers_collection:database@None child=False editors=False type=project_write id_ok=True hash_ok=True\n"
        "call insert_layer.execute_default('database', 'Default', 1)\n"
        "value '42'\n"
        "record default_layers_collection:database@None update\n"
        "created=('42',) maps=(('default_layers', (('0', '42'),)),)\n"
        "updated  deleted \n"
        "pages=() conditions=() families=('default_layers',)\n"
    ),
    "queue_default_layers_delete": (
        "request project_write surface=default-layers-dialog bid=None page=''\n"
        "resources default_layers_collection:database@None\n"
        "dependencies \n"
        'payload save_default_layers {"layer_uids":["40","41"],"operation":"delete"}\n'
        "lease=False\n"
        "outcome committed\n"
        "executed default_layers_collection:database@None child=False editors=False type=project_write id_ok=True hash_ok=True\n"
        "call delete_layer.execute_default('database', '40')\n"
        "call delete_layer.execute_default('database', '41')\n"
        "value True\n"
        "record default_layers_collection:database@None update\n"
        "created=() maps=()\n"
        "updated  deleted default_layers_collection:40@None,default_layers_collection:41@None\n"
        "pages=() conditions=() families=('default_layers',)\n"
    ),
    "queue_default_layer_update rename": (
        "request project_write surface=default-layers-dialog bid=None page=''\n"
        "resources default_layers_collection:database@None\n"
        "dependencies \n"
        'payload save_default_layers {"layer_uid":40,"name":"Walls","operation":"rename"}\n'
        "lease=False\n"
        "outcome committed\n"
        "executed default_layers_collection:database@None child=False editors=False type=project_write id_ok=True hash_ok=True\n"
        "call update_layer_name.execute_default('database', '40', 'Walls')\n"
        "value True\n"
        "record default_layers_collection:database@None update\n"
        "created=() maps=()\n"
        "updated default_layers_collection:database@None deleted \n"
        "pages=() conditions=() families=('default_layers',)\n"
    ),
    "queue_default_layer_update show": (
        "request project_write surface=default-layers-dialog bid=None page=''\n"
        "resources default_layers_collection:database@None\n"
        "dependencies \n"
        'payload save_default_layers {"layer_uid":"40","operation":"show","show":0}\n'
        "lease=False\n"
        "outcome committed\n"
        "executed default_layers_collection:database@None child=False editors=False type=project_write id_ok=True hash_ok=True\n"
        "call update_layer_show.execute_default('database', '40', False)\n"
        "value True\n"
        "record default_layers_collection:database@None update\n"
        "created=() maps=()\n"
        "updated default_layers_collection:database@None deleted \n"
        "pages=() conditions=() families=('default_layers',)\n"
    ),
    "queue_default_layer_update show_all": (
        "request project_write surface=default-layers-dialog bid=None page=''\n"
        "resources default_layers_collection:database@None\n"
        "dependencies \n"
        'payload save_default_layers {"operation":"show_all","show":1}\n'
        "lease=False\n"
        "outcome committed\n"
        "executed default_layers_collection:database@None child=False editors=False type=project_write id_ok=True hash_ok=True\n"
        "call update_all_layers_show.execute_default('database', True)\n"
        "value True\n"
        "record default_layers_collection:database@None update\n"
        "created=() maps=()\n"
        "updated default_layers_collection:database@None deleted \n"
        "pages=() conditions=() families=('default_layers',)\n"
    ),
    "queue_default_layer_update reorder": (
        "request project_write surface=default-layers-dialog bid=None page=''\n"
        "resources default_layers_collection:database@None\n"
        "dependencies \n"
        'payload save_default_layers {"layer_uid":"40","neighbor_uid":"41","operation":"reorder"}\n'
        "lease=False\n"
        "outcome committed\n"
        "executed default_layers_collection:database@None child=False editors=False type=project_write id_ok=True hash_ok=True\n"
        "call swap_layer_sequence.execute_default('database', '40', '41')\n"
        "value True\n"
        "record default_layers_collection:database@None update\n"
        "created=() maps=()\n"
        "updated default_layers_collection:database@None deleted \n"
        "pages=() conditions=() families=('default_layers',)\n"
    ),
    "queue_job_statuses_save": (
        "request project_write surface=job_statuses-dialog bid=None page=''\n"
        "resources job_status:3@None,job_status:4@None\n"
        "dependencies job_statuses_collection:database@None,projects_collection:database@None\n"
        'payload save_job_statuses {"deleted_uids":["3"],"new":[{"name":"Open","uid":"n"}],"updated":[{"name":"Won","uid":"4"}]}\n'
        "lease=False\n"
        "outcome committed\n"
        "executed job_status:3@None,job_status:4@None,job_statuses_collection:database@None,projects_collection:database@None child=False editors=False type=project_write id_ok=True hash_ok=True\n"
        "call save_job_statuses.execute('database', {'new': [{'uid': 'n', 'name': 'Open'}], 'updated': [{'uid': '4', 'name': 'Won'}], 'deleted_uids': ['3']})\n"
        "value {'uid_map': {'n': '5'}, 'created_resources': (ResourceRef(resource_type='job_status', resource_id='5', bid_uid=None),)}\n"
        "record job_status:3@None delete\n"
        "record job_status:4@None update\n"
        "record job_status:5@None create\n"
        "record job_statuses_collection:database@None update\n"
        "record projects_collection:database@None update\n"
        "created=('5',) maps=(('job_statuses', (('n', '5'),)),)\n"
        "updated job_status:4@None deleted job_status:3@None\n"
        "pages=() conditions=() families=('job_statuses', 'hierarchy')\n"
    ),
    "queue_employees_save": (
        "request project_write surface=employees-dialog bid=None page=''\n"
        "resources employees_collection:database@None\n"
        "dependencies employees_collection:database@None,projects_collection:database@None\n"
        'payload save_employees {"deleted_uids":[],"new":[{"address1":"","address2":"","city":"","email":"","employee_no":"","first_name":"Ava","home_phone":"","last_name":"","mobile_phone":"","pay_class_uid":"","state":"","uid":"n","zip":""}],"updated":[]}\n'
        "lease=False\n"
        "outcome committed\n"
        "executed employees_collection:database@None,projects_collection:database@None child=False editors=False type=project_write id_ok=True hash_ok=True\n"
        "call save_employees.execute('database', {'new': [Employee(uid='n', employee_no='', first_name='Ava', last_name='', address1='', address2='', city='', state='', zip='', home_phone='', mobile_phone='', email='', pay_class_uid='')], 'updated': [], 'deleted_uids': []})\n"
        "value {'uid_map': {'n': '6'}, 'created_resources': (ResourceRef(resource_type='employee', resource_id='6', bid_uid=None),)}\n"
        "record employee:6@None create\n"
        "record employees_collection:database@None update\n"
        "record projects_collection:database@None update\n"
        "created=('6',) maps=(('employees', (('n', '6'),)),)\n"
        "updated  deleted \n"
        "pages=() conditions=() families=('employees', 'hierarchy')\n"
    ),
    "queue_pay_classes_save": (
        "request project_write surface=pay_classes-dialog bid=None page=''\n"
        "resources pay_classes_collection:database@None\n"
        "dependencies employees_collection:database@None,pay_classes_collection:database@None\n"
        'payload save_pay_classes {"deleted_uids":[],"new":[{"name":"Field","uid":"n"}],"updated":[]}\n'
        "lease=False\n"
        "outcome committed\n"
        "executed employees_collection:database@None,pay_classes_collection:database@None child=False editors=False type=project_write id_ok=True hash_ok=True\n"
        "call save_pay_classes.execute('database', {'new': [{'uid': 'n', 'name': 'Field'}], 'updated': [], 'deleted_uids': []})\n"
        "value {'uid_map': {'n': '7'}, 'created_resources': (ResourceRef(resource_type='pay_class', resource_id='7', bid_uid=None),)}\n"
        "record employees_collection:database@None update\n"
        "record pay_class:7@None create\n"
        "record pay_classes_collection:database@None update\n"
        "created=('7',) maps=(('pay_classes', (('n', '7'),)),)\n"
        "updated  deleted \n"
        "pages=() conditions=() families=('pay_classes', 'employees')\n"
    ),
    "queue_pages_delete": (
        "request project_write surface=main-plan bid=7 page=''\n"
        "resources annotation:rect/20-a@7,annotation:rect/21-a@7,page:20@7,page:21@7,takeoff:20-t@7,takeoff:21-t@7\n"
        "dependencies annotations_collection:7@7,pages_collection:7@7,takeoffs_collection:7@7\n"
        'payload delete_pages {"page_uids":["20","21"]}\n'
        "lease=False\n"
        "outcome committed\n"
        "executed annotation:rect/20-a@7,annotation:rect/21-a@7,annotations_collection:7@7,page:20@7,page:21@7,pages_collection:7@7,takeoff:20-t@7,takeoff:21-t@7,takeoffs_collection:7@7 child=False editors=False type=project_write id_ok=True hash_ok=True\n"
        "call delete_pages.execute('database', ['20', '21'])\n"
        "value True\n"
        "record annotation:rect/20-a@7 delete\n"
        "record annotation:rect/21-a@7 delete\n"
        "record annotations_collection:7@7 update\n"
        "record page:20@7 delete\n"
        "record page:21@7 delete\n"
        "record pages_collection:7@7 update\n"
        "record takeoff:20-t@7 delete\n"
        "record takeoff:21-t@7 delete\n"
        "record takeoffs_collection:7@7 update\n"
        "created=() maps=()\n"
        "updated  deleted annotation:rect/20-a@7,annotation:rect/21-a@7,page:20@7,page:21@7,takeoff:20-t@7,takeoff:21-t@7\n"
        "pages=('20', '21') conditions=() families=('pages', 'takeoffs', 'annotations')\n"
    ),
    "queue_pages_delete single": (
        "request project_write surface=page-dialog bid=7 page='20'\n"
        "resources annotation:rect/20-a@7,page:20@7,takeoff:20-t@7\n"
        "dependencies annotations_collection:7@7,pages_collection:7@7,takeoffs_collection:7@7\n"
        'payload delete_pages {"page_uids":["20"]}\n'
        "lease=False\n"
        "outcome committed\n"
        "executed annotation:rect/20-a@7,annotations_collection:7@7,page:20@7,pages_collection:7@7,takeoff:20-t@7,takeoffs_collection:7@7 child=False editors=False type=project_write id_ok=True hash_ok=True\n"
        "call delete_pages.execute('database', ['20'])\n"
        "value True\n"
        "record annotation:rect/20-a@7 delete\n"
        "record annotations_collection:7@7 update\n"
        "record page:20@7 delete\n"
        "record pages_collection:7@7 update\n"
        "record takeoff:20-t@7 delete\n"
        "record takeoffs_collection:7@7 update\n"
        "created=() maps=()\n"
        "updated  deleted annotation:rect/20-a@7,page:20@7,takeoff:20-t@7\n"
        "pages=('20',) conditions=() families=('pages', 'takeoffs', 'annotations')\n"
    ),
    "queue_condition_create": (
        "request project_write surface=condition-sidebar bid=7 page=''\n"
        "resources conditions_collection:7@7\n"
        "dependencies condition_folder:f1@7,condition_type:3@None,condition_types_collection:database@None,layer:40@7\n"
        'payload create_condition {"spec":{"backout":false,"calc_type1":0,"calc_type2":0,"calc_type3":0,"cdn_type_uid":"3","color_fill":0,"condition_type":0,"depth":0.0,"display_dimension":false,"display_grid_while_drawing":false,"display_name":false,"display_size":100.0,"drop_run":false,"drop_value":0.0,"folder_uid":"f1","gap":0.0,"grid":false,"grid_size1":0.0,"grid_size2":0.0,"height":0.0,"is_curved_segment":false,"layer_uid":"40","name":"C","notes":"","pattern":0,"rise":0.0,"round_quantity":false,"round_up":0.0,"run":0.0,"shape":-1,"spacing":4.0,"thickness":4.0,"trim":false,"uom1":0,"uom2":-1,"uom3":-1,"width":12.0}}\n'
        "lease=False\n"
        "outcome committed\n"
        "executed condition_folder:f1@7,condition_type:3@None,condition_types_collection:database@None,conditions_collection:7@7,layer:40@7 child=False editors=False type=project_write id_ok=True hash_ok=True\n"
        "call insert_condition.execute('database', '7', CreateConditionSpec(name='C', condition_type=0, backout=False, cdn_type_uid='3', layer_uid='40', height=0.0, width=12.0, depth=0.0, thickness=4.0, rise=0.0, run=0.0, display_size=100.0, shape=-1, pattern=0, spacing=4.0, color_fill=0, uom1=0, uom2=-1, uom3=-1, calc_type1=0, calc_type2=0, calc_type3=0, notes='', drop_run=False, drop_value=0.0, round_quantity=False, round_up=0.0, trim=False, is_curved_segment=False, grid=False, grid_size1=0.0, grid_size2=0.0, gap=0.0, display_dimension=False, display_name=False, display_grid_while_drawing=False, folder_uid='f1'))\n"
        "value 'c9'\n"
        "record condition:c9@7 create\n"
        "record conditions_collection:7@7 update\n"
        "created=('c9',) maps=(('conditions', (('0', 'c9'),)),)\n"
        "updated  deleted \n"
        "pages=() conditions=('c9',) families=('conditions',)\n"
    ),
    "queue_condition_create plain": (
        "request project_write surface=condition-sidebar bid=7 page=''\n"
        "resources conditions_collection:7@7\n"
        "dependencies \n"
        'payload create_condition {"spec":{"backout":false,"calc_type1":0,"calc_type2":0,"calc_type3":0,"cdn_type_uid":null,"color_fill":0,"condition_type":0,"depth":0.0,"display_dimension":false,"display_grid_while_drawing":false,"display_name":false,"display_size":100.0,"drop_run":false,"drop_value":0.0,"folder_uid":null,"gap":0.0,"grid":false,"grid_size1":0.0,"grid_size2":0.0,"height":0.0,"is_curved_segment":false,"layer_uid":null,"name":"C","notes":"","pattern":0,"rise":0.0,"round_quantity":false,"round_up":0.0,"run":0.0,"shape":-1,"spacing":4.0,"thickness":4.0,"trim":false,"uom1":0,"uom2":-1,"uom3":-1,"width":12.0}}\n'
        "lease=False\n"
        "outcome committed\n"
        "executed conditions_collection:7@7 child=False editors=False type=project_write id_ok=True hash_ok=True\n"
        "call insert_condition.execute('database', '7', CreateConditionSpec(name='C', condition_type=0, backout=False, cdn_type_uid=None, layer_uid=None, height=0.0, width=12.0, depth=0.0, thickness=4.0, rise=0.0, run=0.0, display_size=100.0, shape=-1, pattern=0, spacing=4.0, color_fill=0, uom1=0, uom2=-1, uom3=-1, calc_type1=0, calc_type2=0, calc_type3=0, notes='', drop_run=False, drop_value=0.0, round_quantity=False, round_up=0.0, trim=False, is_curved_segment=False, grid=False, grid_size1=0.0, grid_size2=0.0, gap=0.0, display_dimension=False, display_name=False, display_grid_while_drawing=False, folder_uid=None))\n"
        "value 'c9'\n"
        "record condition:c9@7 create\n"
        "record conditions_collection:7@7 update\n"
        "created=('c9',) maps=(('conditions', (('0', 'c9'),)),)\n"
        "updated  deleted \n"
        "pages=() conditions=('c9',) families=('conditions',)\n"
    ),
    "queue_conditions_delete": (
        "request project_write surface=condition-sidebar bid=7 page=''\n"
        "resources condition:c1@7,condition:c2@7\n"
        "dependencies conditions_collection:7@7\n"
        'payload delete_conditions {"condition_uids":["c1","c2"]}\n'
        "lease=False\n"
        "outcome committed\n"
        "executed condition:c1@7,condition:c2@7,conditions_collection:7@7 child=False editors=False type=project_write id_ok=True hash_ok=True\n"
        "call delete_conditions.execute('database', '7', ['c1', 'c2'])\n"
        "value True\n"
        "record condition:c1@7 delete\n"
        "record condition:c2@7 delete\n"
        "record conditions_collection:7@7 update\n"
        "created=() maps=()\n"
        "updated  deleted condition:c1@7,condition:c2@7\n"
        "pages=() conditions=('c1', 'c2') families=('conditions',)\n"
    ),
    "queue_conditions_duplicate": (
        "request project_write surface=condition-sidebar bid=7 page=''\n"
        "resources conditions_collection:7@7\n"
        "dependencies condition:c1@7,condition:c2@7,condition_folder:f1@7,condition_type:3@None,condition_types_collection:database@None\n"
        'payload duplicate_conditions {"condition_uids":["c1","c2"],"reassign_takeoffs":null,"takeoff_ownership":[],"target_changes":{"cdn_type_uid":"3","folder_uid":"f1","name":"X"}}\n'
        "lease=False\n"
        "outcome committed\n"
        "executed condition:c1@7,condition:c2@7,condition_folder:f1@7,condition_type:3@None,condition_types_collection:database@None,conditions_collection:7@7 child=False editors=False type=project_write id_ok=True hash_ok=True\n"
        "call duplicate_conditions.execute('database', '7', ['c1', 'c2'])\n"
        "call update_condition.execute('database', '7', 'c9', UpdateConditionDto{'cdn_type_uid': '3', 'folder_uid': 'f1', 'name': 'X'})\n"
        "call update_condition.execute('database', '7', 'c10', UpdateConditionDto{'cdn_type_uid': '3', 'folder_uid': 'f1', 'name': 'X'})\n"
        "value ('c9', 'c10')\n"
        "record condition:c10@7 create\n"
        "record condition:c9@7 create\n"
        "record conditions_collection:7@7 update\n"
        "created=('c9', 'c10') maps=(('conditions', (('c1', 'c9'), ('c2', 'c10'))),)\n"
        "updated  deleted \n"
        "pages=() conditions=('c9', 'c10') families=('conditions',)\n"
    ),
    "queue_conditions_update": (
        "request project_write surface=condition-sidebar bid=7 page=''\n"
        "resources condition:c1@7,condition:c2@7\n"
        "dependencies condition_folder:f1@7,condition_type:3@None,condition_types_collection:database@None,layer:40@7\n"
        'payload update_conditions {"changes":{"cdn_type_uid":"3","folder_uid":"f1","layer_uid":"40","z_value":1.5},"condition_uids":["c1","c2"]}\n'
        "lease=False\n"
        "outcome committed\n"
        "executed condition:c1@7,condition:c2@7,condition_folder:f1@7,condition_type:3@None,condition_types_collection:database@None,layer:40@7 child=False editors=False type=project_write id_ok=True hash_ok=True\n"
        "call update_condition.execute('database', '7', 'c1', UpdateConditionDto{'cdn_type_uid': '3', 'folder_uid': 'f1', 'layer_uid': '40', 'z_value': 1.5})\n"
        "call update_condition.execute('database', '7', 'c2', UpdateConditionDto{'cdn_type_uid': '3', 'folder_uid': 'f1', 'layer_uid': '40', 'z_value': 1.5})\n"
        "value True\n"
        "record condition:c1@7 update fields=['cdn_type_uid', 'folder_uid', 'layer_uid', 'z_value']\n"
        "record condition:c2@7 update fields=['cdn_type_uid', 'folder_uid', 'layer_uid', 'z_value']\n"
        "created=() maps=()\n"
        "updated condition:c1@7,condition:c2@7 deleted \n"
        "pages=() conditions=('c1', 'c2') families=('conditions',)\n"
    ),
    "queue_conditions_update clearing type": (
        "request project_write surface=condition-sidebar bid=7 page=''\n"
        "resources condition:c1@7\n"
        "dependencies condition_types_collection:database@None\n"
        'payload update_conditions {"changes":{"cdn_type_uid":null},"condition_uids":["c1"]}\n'
        "lease=False\n"
        "outcome committed\n"
        "executed condition:c1@7,condition_types_collection:database@None child=False editors=False type=project_write id_ok=True hash_ok=True\n"
        "call update_condition.execute('database', '7', 'c1', UpdateConditionDto{'cdn_type_uid': None})\n"
        "value True\n"
        "record condition:c1@7 update fields=['cdn_type_uid']\n"
        "created=() maps=()\n"
        "updated condition:c1@7 deleted \n"
        "pages=() conditions=('c1',) families=('conditions',)\n"
    ),
    "queue_conditions_renumber": (
        "request project_write surface=condition-sidebar bid=7 page=''\n"
        "resources conditions_collection:7@7\n"
        "dependencies condition:c1@7,condition:c2@7\n"
        'payload renumber_conditions {"condition_uids":["c2","c1"]}\n'
        "lease=False\n"
        "outcome committed\n"
        "executed condition:c1@7,condition:c2@7,conditions_collection:7@7 child=False editors=False type=project_write id_ok=True hash_ok=True\n"
        "call renumber_conditions.execute('database', '7', ['c2', 'c1'])\n"
        "value True\n"
        "record condition:c1@7 reorder fields=['ref_no']\n"
        "record condition:c2@7 reorder fields=['ref_no']\n"
        "record conditions_collection:7@7 reorder\n"
        "created=() maps=()\n"
        "updated condition:c2@7,condition:c1@7 deleted \n"
        "pages=() conditions=('c2', 'c1') families=('conditions',)\n"
    ),
    "queue_condition_folder_create": (
        "request project_write surface=condition-sidebar bid=7 page=''\n"
        "resources conditions_collection:7@7\n"
        "dependencies condition_folder:f1@7\n"
        'payload create_condition_folder {"name":"Walls","parent_uid":"f1"}\n'
        "lease=False\n"
        "outcome committed\n"
        "executed condition_folder:f1@7,conditions_collection:7@7 child=False editors=False type=project_write id_ok=True hash_ok=True\n"
        "call insert_condition_folder.execute('database', '7', 'Walls', 'f1')\n"
        "value 'f9'\n"
        "record condition_folder:f9@7 create\n"
        "record conditions_collection:7@7 update\n"
        "created=('f9',) maps=(('condition_folders', (('0', 'f9'),)),)\n"
        "updated  deleted \n"
        "pages=() conditions=() families=('conditions',)\n"
    ),
    "queue_condition_folder_create root": (
        "request project_write surface=condition-sidebar bid=7 page=''\n"
        "resources conditions_collection:7@7\n"
        "dependencies \n"
        'payload create_condition_folder {"name":"Walls","parent_uid":null}\n'
        "lease=False\n"
        "outcome committed\n"
        "executed conditions_collection:7@7 child=False editors=False type=project_write id_ok=True hash_ok=True\n"
        "call insert_condition_folder.execute('database', '7', 'Walls', None)\n"
        "value 'f9'\n"
        "record condition_folder:f9@7 create\n"
        "record conditions_collection:7@7 update\n"
        "created=('f9',) maps=(('condition_folders', (('0', 'f9'),)),)\n"
        "updated  deleted \n"
        "pages=() conditions=() families=('conditions',)\n"
    ),
    "queue_condition_folder_rename": (
        "request project_write surface=condition-sidebar bid=7 page=''\n"
        "resources condition_folder:f1@7\n"
        "dependencies \n"
        'payload rename_condition_folder {"folder_uid":"f1","name":"N"}\n'
        "lease=False\n"
        "outcome committed\n"
        "executed condition_folder:f1@7 child=False editors=False type=project_write id_ok=True hash_ok=True\n"
        "call rename_condition_folder.execute('database', 'f1', 'N')\n"
        "value True\n"
        "record condition_folder:f1@7 update fields=['name']\n"
        "created=() maps=()\n"
        "updated condition_folder:f1@7 deleted \n"
        "pages=() conditions=() families=('conditions',)\n"
    ),
    "queue_condition_folders_delete": (
        "request project_write surface=condition-sidebar bid=7 page=''\n"
        "resources condition_folder:f1@7,condition_folder:f2@7\n"
        "dependencies conditions_collection:7@7\n"
        'payload delete_condition_folders {"folder_uids":["f1","f2"]}\n'
        "lease=False\n"
        "outcome committed\n"
        "executed condition_folder:f1@7,condition_folder:f2@7,conditions_collection:7@7 child=False editors=False type=project_write id_ok=True hash_ok=True\n"
        "call delete_condition_folders.execute('database', ['f1', 'f2'])\n"
        "value True\n"
        "record condition_folder:f1@7 delete\n"
        "record condition_folder:f2@7 delete\n"
        "record conditions_collection:7@7 update\n"
        "created=() maps=()\n"
        "updated  deleted condition_folder:f1@7,condition_folder:f2@7\n"
        "pages=() conditions=() families=('conditions',)\n"
    ),
    "queue_layer_insert": (
        "request project_write surface=desktop bid=7 page=''\n"
        "resources layers_collection:7@7\n"
        "dependencies \n"
        'payload insert_layer {"after_sequence":2,"name":"Layer"}\n'
        "lease=False\n"
        "outcome committed\n"
        "executed layers_collection:7@7 child=False editors=False type=project_write id_ok=True hash_ok=True\n"
        "call insert_layer.execute('database', '7', 'Layer', 2)\n"
        "value '41'\n"
        "record layer:41@7 create\n"
        "record layers_collection:7@7 update\n"
        "created=('41',) maps=(('layers', (('0', '41'),)),)\n"
        "updated  deleted \n"
        "pages=() conditions=() families=('layers',)\n"
    ),
    "queue_layer_delete": (
        "request project_write surface=desktop bid=7 page=''\n"
        "resources layer:40@7\n"
        "dependencies layers_collection:7@7\n"
        'payload delete_layers {"layer_uids":["40"]}\n'
        "lease=False\n"
        "outcome committed\n"
        "executed layer:40@7,layers_collection:7@7 child=False editors=False type=project_write id_ok=True hash_ok=True\n"
        "call delete_layer.execute('database', '40')\n"
        "value True\n"
        "record layer:40@7 delete\n"
        "record layers_collection:7@7 update\n"
        "created=() maps=()\n"
        "updated  deleted layer:40@7\n"
        "pages=() conditions=() families=('layers',)\n"
    ),
    "queue_layers_delete": (
        "request project_write surface=desktop bid=7 page=''\n"
        "resources layer:40@7,layer:41@7\n"
        "dependencies layers_collection:7@7\n"
        'payload delete_layers {"layer_uids":["40","41"]}\n'
        "lease=False\n"
        "outcome committed\n"
        "executed layer:40@7,layer:41@7,layers_collection:7@7 child=False editors=False type=project_write id_ok=True hash_ok=True\n"
        "call delete_layer.execute('database', '40')\n"
        "call delete_layer.execute('database', '41')\n"
        "value True\n"
        "record layer:40@7 delete\n"
        "record layer:41@7 delete\n"
        "record layers_collection:7@7 update\n"
        "created=() maps=()\n"
        "updated  deleted layer:40@7,layer:41@7\n"
        "pages=() conditions=() families=('layers',)\n"
    ),
    "queue_layer_reorder": (
        "request project_write surface=desktop bid=7 page=''\n"
        "resources layer:40@7,layer:41@7\n"
        "dependencies layers_collection:7@7\n"
        'payload swap_layers {"layer_uid_a":"40","layer_uid_b":"41"}\n'
        "lease=False\n"
        "outcome committed\n"
        "executed layer:40@7,layer:41@7,layers_collection:7@7 child=False editors=False type=project_write id_ok=True hash_ok=True\n"
        "call swap_layer_sequence.execute('database', '40', '41')\n"
        "value True\n"
        "record layer:40@7 reorder\n"
        "record layer:41@7 reorder\n"
        "record layers_collection:7@7 reorder\n"
        "created=() maps=()\n"
        "updated layer:40@7,layer:41@7 deleted \n"
        "pages=() conditions=() families=('layers',)\n"
    ),
    "queue_all_layers_show": (
        "request project_write surface=main-plan bid=7 page=''\n"
        "resources layers_collection:7@7\n"
        "dependencies \n"
        'payload update_all_layers_show {"layer_uids":["40","41"],"show":false}\n'
        "lease=False\n"
        "outcome committed\n"
        "executed layers_collection:7@7 child=False editors=False type=project_write id_ok=True hash_ok=True\n"
        "call update_all_layers_show.execute('database', '7', False, ['40', '41'])\n"
        "value True\n"
        "record layers_collection:7@7 update fields=['show']\n"
        "created=() maps=()\n"
        "updated layers_collection:7@7 deleted \n"
        "pages=() conditions=() families=('layers',)\n"
    ),
    "queue_layer_rename": (
        "request project_write surface=desktop bid=7 page=''\n"
        "resources layer:40@7\n"
        "dependencies \n"
        'payload rename_layer {"layer_uid":"40","name":"Walls"}\n'
        "lease=False\n"
        "outcome committed\n"
        "executed layer:40@7 child=False editors=False type=project_write id_ok=True hash_ok=True\n"
        "call update_layer_name.execute('database', '40', 'Walls')\n"
        "value True\n"
        "record layer:40@7 update fields=['name']\n"
        "created=() maps=()\n"
        "updated layer:40@7 deleted \n"
        "pages=() conditions=() families=('layers',)\n"
    ),
    "queue_project_import": (
        "request project_import surface=project-import bid=None page=''\n"
        "resources condition_types_collection:database@None,employees_collection:database@None,job_statuses_collection:database@None,pay_classes_collection:database@None,project_bids:9@None\n"
        "dependencies project:9@None\n"
        "payload ProjectImportPayload(source_path='C:/imports/project.ost', source_kind='ost', source_size=123, source_modified_ns=456, target_project_uid='9')\n"
        "lease=False\n"
        "outcome committed\n"
        "executed condition_types_collection:database@None,employees_collection:database@None,job_statuses_collection:database@None,pay_classes_collection:database@None,project:9@None,project_bids:9@None child=False editors=False type=project_import id_ok=True hash_ok=True\n"
        "value {'project_uids': {'target': '9'}, 'bid_uids': {'b': '10'}, 'page_uids': {'p': '20'}, 'condition_uids': {'c': '30'}, 'layer_uids': {'l': '40'}, 'area_uids': {'r': '50'}, 'takeoff_uids': {'t': '60'}, 'annotation_uids': {'a': '70'}}\n"
        "created=('10', '20', '30', '40', '50', '60', '70') maps=(('projects', (('target', '9'),)), ('bids', (('b', '10'),)), ('pages', (('p', '20'),)), ('conditions', (('c', '30'),)), ('layers', (('l', '40'),)), ('areas', (('r', '50'),)), ('takeoffs', (('t', '60'),)), ('annotations', (('a', '70'),)))\n"
        "updated project_bids:9@None,condition_types_collection:database@None,job_statuses_collection:database@None,employees_collection:database@None,pay_classes_collection:database@None deleted \n"
        "pages=('20',) conditions=('30',) families=('hierarchy', 'conditions', 'areas', 'pages', 'layers', 'takeoffs', 'annotations', 'cover_sheet', 'master_data')\n"
    ),
    "queue_project_import orphan": (
        "request project_import surface=project-import bid=None page=''\n"
        "resources condition_types_collection:database@None,employees_collection:database@None,job_statuses_collection:database@None,pay_classes_collection:database@None,project_bids:orphan@None\n"
        "dependencies \n"
        "payload ProjectImportPayload(source_path='C:/imports/project.ost', source_kind='ost', source_size=123, source_modified_ns=456, target_project_uid=None)\n"
        "lease=False\n"
        "outcome committed\n"
        "executed condition_types_collection:database@None,employees_collection:database@None,job_statuses_collection:database@None,pay_classes_collection:database@None,project_bids:orphan@None child=False editors=False type=project_import id_ok=True hash_ok=True\n"
        "value {'project_uids': {'target': '9'}, 'bid_uids': {'b': '10'}, 'page_uids': {'p': '20'}, 'condition_uids': {'c': '30'}, 'layer_uids': {'l': '40'}, 'area_uids': {'r': '50'}, 'takeoff_uids': {'t': '60'}, 'annotation_uids': {'a': '70'}}\n"
        "created=('10', '20', '30', '40', '50', '60', '70') maps=(('projects', (('target', '9'),)), ('bids', (('b', '10'),)), ('pages', (('p', '20'),)), ('conditions', (('c', '30'),)), ('layers', (('l', '40'),)), ('areas', (('r', '50'),)), ('takeoffs', (('t', '60'),)), ('annotations', (('a', '70'),)))\n"
        "updated project_bids:orphan@None,condition_types_collection:database@None,job_statuses_collection:database@None,employees_collection:database@None,pay_classes_collection:database@None deleted \n"
        "pages=('20',) conditions=('30',) families=('hierarchy', 'conditions', 'areas', 'pages', 'layers', 'takeoffs', 'annotations', 'cover_sheet', 'master_data')\n"
    ),
}
_PLAN_LOCAL_EXPECTED = {
    "delete_local mixed": (
        "result outcome=committed created=() message='' commit_attempted=True\n"
        "created=() maps=()\n"
        "updated  deleted annotation:line/a2@7,annotation:rect/a1@7,takeoff:30@7,takeoff:31@7\n"
        "pages=('20', '21') conditions=() families=('takeoffs', 'annotations')\n"
        "call delete_annotations.execute('C:/jobs/test.mdb', [('a1', 'rect'), ('a2', 'line')])\n"
        "call delete_takeoffs.execute('C:/jobs/test.mdb', ['30', '31'])\n"
        "request annotation:line/a2@7,annotation:rect/a1@7,annotations_collection:7@7,condition:10@7,page:20@7,page:21@7,takeoff:30@7,takeoff:31@7,takeoffs_collection:7@7 child=False editors=False type=plan_items_delete\n"
        "value True\n"
        "record annotation:line/a2@7 delete\n"
        "record annotation:rect/a1@7 delete\n"
        "record annotations_collection:7@7 update\n"
        "record takeoff:30@7 delete\n"
        "record takeoff:31@7 delete\n"
        "record takeoffs_collection:7@7 update\n"
        "reload C:/jobs/test.mdb\n"
        "event REFRESH\n"
    ),
    "delete_local takeoffs only without refresh": (
        "result outcome=committed created=() message='' commit_attempted=True\n"
        "created=() maps=()\n"
        "updated  deleted takeoff:30@7\n"
        "pages=('20',) conditions=() families=('takeoffs',)\n"
        "call delete_takeoffs.execute('C:/jobs/test.mdb', ['30'])\n"
        "request page:20@7,takeoff:30@7,takeoffs_collection:7@7 child=False editors=False type=plan_items_delete\n"
        "value True\n"
        "record takeoff:30@7 delete\n"
        "record takeoffs_collection:7@7 update\n"
    ),
    "delete_local annotations only": (
        "result outcome=committed created=() message='' commit_attempted=True\n"
        "created=() maps=()\n"
        "updated  deleted annotation:rect/a1@7\n"
        "pages=() conditions=() families=('annotations',)\n"
        "call delete_annotations.execute('C:/jobs/test.mdb', [('a1', 'rect')])\n"
        "request annotation:rect/a1@7,annotations_collection:7@7 child=False editors=False type=plan_items_delete\n"
        "value True\n"
        "record annotation:rect/a1@7 delete\n"
        "record annotations_collection:7@7 update\n"
        "reload C:/jobs/test.mdb\n"
        "event REFRESH\n"
    ),
    "geometry_local mixed": (
        "result outcome=committed created=() message='' commit_attempted=True\n"
        "created=() maps=()\n"
        "updated annotation:rect/a1@7,takeoff:30@7,takeoff:31@7,takeoff:32@7 deleted \n"
        "pages=('20', '21') conditions=() families=('takeoffs', 'annotations')\n"
        "call save_takeoff_positions.execute('C:/jobs/test.mdb', [('30', [1.0, 2.0]), ('31', [3.5, 4.0])])\n"
        "call save_takeoff_rotations.execute('C:/jobs/test.mdb', [('30', 90.0), ('32', 45.5)])\n"
        "call save_annotation_positions.execute('C:/jobs/test.mdb', [('a1', 'rect', [1.0, 2.0, 3.0, 4.0])])\n"
        "request annotation:rect/a1@7,condition:10@7,page:20@7,page:21@7,takeoff:30@7,takeoff:31@7,takeoff:32@7 child=False editors=False type=plan_geometry\n"
        "verify ('C:/jobs/test.mdb', '7', ('30', '31', '32'), (('a1', 'rect'),), ())\n"
        "value True\n"
        "record annotation:rect/a1@7 update fields=['position']\n"
        "record takeoff:30@7 update fields=['position', 'rotation']\n"
        "record takeoff:31@7 update fields=['position']\n"
        "record takeoff:32@7 update fields=['rotation']\n"
        "reload C:/jobs/test.mdb\n"
        "event REFRESH\n"
    ),
    "geometry_local rotation only": (
        "result outcome=committed created=() message='' commit_attempted=True\n"
        "created=() maps=()\n"
        "updated takeoff:32@7 deleted \n"
        "pages=('21',) conditions=() families=('takeoffs',)\n"
        "call save_takeoff_rotations.execute('C:/jobs/test.mdb', [('32', 45.0)])\n"
        "request page:21@7,takeoff:32@7 child=False editors=False type=plan_geometry\n"
        "verify ('C:/jobs/test.mdb', '7', ('32',), (), ())\n"
        "value True\n"
        "record takeoff:32@7 update fields=['rotation']\n"
        "reload C:/jobs/test.mdb\n"
        "event REFRESH\n"
    ),
    "geometry_local annotations only without refresh": (
        "result outcome=committed created=() message='' commit_attempted=True\n"
        "created=() maps=()\n"
        "updated annotation:line/a1@7 deleted \n"
        "pages=() conditions=() families=('annotations',)\n"
        "call save_annotation_positions.execute('C:/jobs/test.mdb', [('a1', 'line', [1.0, 2.0])])\n"
        "request annotation:line/a1@7 child=False editors=False type=plan_geometry\n"
        "verify ('C:/jobs/test.mdb', '7', (), (('a1', 'line'),), ())\n"
        "value True\n"
        "record annotation:line/a1@7 update fields=['position']\n"
    ),
    "properties_local takeoff_text": (
        "result outcome=committed created=() message='' commit_attempted=True\n"
        "created=() maps=()\n"
        "updated takeoff:30@7 deleted \n"
        "pages=('20',) conditions=() families=('takeoffs',)\n"
        "call save_takeoff_text_properties.execute('C:/jobs/test.mdb', [('30', {'Text': 'T'})])\n"
        "request page:20@7,takeoff:30@7,takeoff:31@7 child=False editors=False type=takeoff_properties\n"
        "verify ('C:/jobs/test.mdb', '7', ('30', '31'), (), ('30', '31'))\n"
        "value True\n"
        "record takeoff:30@7 update fields=['text_properties']\n"
        "reload C:/jobs/test.mdb\n"
        "event REFRESH\n"
    ),
    "properties_local takeoff_area": (
        "result outcome=committed created=() message='' commit_attempted=True\n"
        "created=() maps=()\n"
        "updated takeoff:30@7,takeoff:31@7,takeoff:32@7 deleted \n"
        "pages=() conditions=() families=('takeoffs',)\n"
        "call save_takeoffs_area.execute('C:/jobs/test.mdb', ['30', '31'], '5')\n"
        "call save_takeoffs_area.execute('C:/jobs/test.mdb', ['32'], '6')\n"
        "request takeoff:30@7,takeoff:31@7,takeoff:32@7 child=False editors=False type=takeoff_properties\n"
        "verify ('C:/jobs/test.mdb', '7', ('30', '31', '32'), (), ('30', '31', '32'))\n"
        "value True\n"
        "record takeoff:30@7 update fields=['area']\n"
        "record takeoff:31@7 update fields=['area']\n"
        "record takeoff:32@7 update fields=['area']\n"
        "reload C:/jobs/test.mdb\n"
        "event REFRESH\n"
    ),
    "properties_local takeoff_condition": (
        "result outcome=committed created=() message='' commit_attempted=True\n"
        "created=() maps=()\n"
        "updated takeoff:30@7,takeoff:32@7 deleted \n"
        "pages=() conditions=() families=('takeoffs',)\n"
        "call save_takeoffs_condition.execute('C:/jobs/test.mdb', ['30', '32'], '10')\n"
        "request takeoff:30@7,takeoff:31@7,takeoff:32@7 child=False editors=False type=takeoff_properties\n"
        "verify ('C:/jobs/test.mdb', '7', ('30', '31', '32'), (), ('30', '31', '32'))\n"
        "value True\n"
        "record takeoff:30@7 update fields=['condition']\n"
        "record takeoff:32@7 update fields=['condition']\n"
        "reload C:/jobs/test.mdb\n"
        "event REFRESH\n"
    ),
    "properties_local takeoff_negative": (
        "result outcome=committed created=() message='' commit_attempted=True\n"
        "created=() maps=()\n"
        "updated takeoff:30@7,takeoff:31@7,takeoff:32@7 deleted \n"
        "pages=() conditions=() families=('takeoffs',)\n"
        "call set_takeoffs_negative.execute('C:/jobs/test.mdb', ['30', '31'], True)\n"
        "call set_takeoffs_negative.execute('C:/jobs/test.mdb', ['32'], False)\n"
        "request takeoff:30@7,takeoff:31@7,takeoff:32@7 child=False editors=False type=takeoff_properties\n"
        "verify ('C:/jobs/test.mdb', '7', ('30', '31', '32'), (), ('30', '31', '32'))\n"
        "value True\n"
        "record takeoff:30@7 update fields=['negative']\n"
        "record takeoff:31@7 update fields=['negative']\n"
        "record takeoff:32@7 update fields=['negative']\n"
        "reload C:/jobs/test.mdb\n"
        "event REFRESH\n"
    ),
    "properties_local takeoff_curve": (
        "result outcome=committed created=() message='' commit_attempted=True\n"
        "created=() maps=()\n"
        "updated takeoff:30@7 deleted \n"
        "pages=() conditions=() families=('takeoffs',)\n"
        "call set_takeoff_curve.execute('C:/jobs/test.mdb', '30', [1.0, 2.0], 3)\n"
        "request takeoff:30@7,takeoff:31@7 child=False editors=False type=takeoff_properties\n"
        "verify ('C:/jobs/test.mdb', '7', ('30', '31'), (), ('30', '31'))\n"
        "value True\n"
        "record takeoff:30@7 update fields=['position', 'curve']\n"
        "reload C:/jobs/test.mdb\n"
        "event REFRESH\n"
    ),
    "properties_local annotation_text": (
        "result outcome=committed created=() message='' commit_attempted=True\n"
        "created=() maps=()\n"
        "updated annotation:rect/a1@7 deleted \n"
        "pages=() conditions=() families=('annotations',)\n"
        "call save_annotation_text_properties.execute('C:/jobs/test.mdb', [('a1', 'rect', {'Text': 'T'})])\n"
        "request annotation:rect/a1@7 child=False editors=False type=annotation_update\n"
        "verify ('C:/jobs/test.mdb', '7', (), (('a1', 'rect'),), ())\n"
        "value True\n"
        "record annotation:rect/a1@7 update fields=['text_properties']\n"
        "reload C:/jobs/test.mdb\n"
        "event REFRESH\n"
    ),
    "properties_local annotation_style without refresh": (
        "result outcome=committed created=() message='' commit_attempted=True\n"
        "created=() maps=()\n"
        "updated annotation:rect/a1@7 deleted \n"
        "pages=() conditions=() families=('annotations',)\n"
        "call save_annotation_styles.execute('C:/jobs/test.mdb', [('a1', 'rect', {'color': '#112233'})])\n"
        "request annotation:rect/a1@7 child=False editors=False type=annotation_update\n"
        "verify ('C:/jobs/test.mdb', '7', (), (('a1', 'rect'),), ())\n"
        "value True\n"
        "record annotation:rect/a1@7 update fields=['style']\n"
    ),
    "paste_local same bid": (
        "result outcome=committed created=('p-new', 'h-new', 'named-new', 'rect-new') message='' commit_attempted=True\n"
        "created=('p-new', 'h-new', 'named-new', 'rect-new') maps=(('takeoffs', (('hole', 'h-new'), ('parent', 'p-new'))), ('annotations', (('namedview/shared', 'named-new'), ('rect/shared', 'rect-new'))), ('conditions', ()))\n"
        "updated  deleted \n"
        "pages=('p1',) conditions=() families=('takeoffs', 'annotations')\n"
        "call insert_takeoffs.execute('C:/jobs/test.mdb', '7', [InsertTakeoffSpec(condition_uid='c1', page_uid='p1', area_uid='0', position=[0.0, 0.0, 10.0, 0.0], parent_uid='0', curve=-1, rotation=0.0, is_negative=False, raw_extras={}, source_bid_uid=None)])\n"
        "call insert_takeoffs.execute('C:/jobs/test.mdb', '7', [InsertTakeoffSpec(condition_uid='c1', page_uid='p1', area_uid='0', position=[2.0, 2.0, 4.0, 2.0], parent_uid='p-new', curve=-1, rotation=0.0, is_negative=True, raw_extras={}, source_bid_uid=None)])\n"
        "call insert_annotations.execute('C:/jobs/test.mdb', '7', [InsertAnnotationSpec(page_uid='p1', annotation_type='namedview', position=[0.0, 0.0, 1.0, 1.0], color='#000000', width=1.0, properties={}, layer_uid='')], PasteRefRemap(takeoff_uids={'parent': 'p-new', 'hole': 'h-new'}, namedview_uids={'shared': 'named-new'}))\n"
        "call insert_annotations.execute('C:/jobs/test.mdb', '7', [InsertAnnotationSpec(page_uid='p1', annotation_type='rect', position=[1.0, 1.0, 2.0, 2.0], color='#000000', width=1.0, properties={}, layer_uid='')], PasteRefRemap(takeoff_uids={'parent': 'p-new', 'hole': 'h-new'}, namedview_uids={'shared': 'named-new'}))\n"
        "request annotations_collection:7@7,condition:c1@7,page:p1@7,takeoffs_collection:7@7 child=False editors=False type=plan_items_paste\n"
        "value {'takeoff_uids': {'parent': 'p-new', 'hole': 'h-new'}, 'annotation_uids': {'namedview/shared': 'named-new', 'rect/shared': 'rect-new'}, 'condition_uids': {}}\n"
        "record annotation:namedview/named-new@7 create\n"
        "record annotation:rect/rect-new@7 create\n"
        "record annotations_collection:7@7 update\n"
        "record takeoff:h-new@7 create\n"
        "record takeoff:p-new@7 create\n"
        "record takeoffs_collection:7@7 update\n"
        "reload C:/jobs/test.mdb\n"
        "event REFRESH\n"
    ),
    "paste_local cross bid": (
        "result outcome=committed created=('p-new', 'h-new', 'named-new', 'rect-new') message='' commit_attempted=True\n"
        "created=('p-new', 'h-new', 'named-new', 'rect-new') maps=(('takeoffs', (('hole', 'h-new'), ('parent', 'p-new'))), ('annotations', (('namedview/shared', 'named-new'), ('rect/shared', 'rect-new'))), ('conditions', (('c1', 'c9'),)))\n"
        "updated  deleted \n"
        "pages=('p1',) conditions=('c9',) families=('takeoffs', 'annotations')\n"
        "call duplicate_conditions.execute_to_bid('C:/jobs/test.mdb', '6', '7', ['c1'])\n"
        "call insert_takeoffs.execute('C:/jobs/test.mdb', '7', [InsertTakeoffSpec(condition_uid='c9', page_uid='p1', area_uid='0', position=[0.0, 0.0, 10.0, 0.0], parent_uid='0', curve=-1, rotation=0.0, is_negative=False, raw_extras={}, source_bid_uid=None)])\n"
        "call insert_takeoffs.execute('C:/jobs/test.mdb', '7', [InsertTakeoffSpec(condition_uid='c9', page_uid='p1', area_uid='0', position=[2.0, 2.0, 4.0, 2.0], parent_uid='p-new', curve=-1, rotation=0.0, is_negative=True, raw_extras={}, source_bid_uid=None)])\n"
        "call insert_annotations.execute('C:/jobs/test.mdb', '7', [InsertAnnotationSpec(page_uid='p1', annotation_type='namedview', position=[0.0, 0.0, 1.0, 1.0], color='#000000', width=1.0, properties={}, layer_uid='')], PasteRefRemap(takeoff_uids={'parent': 'p-new', 'hole': 'h-new'}, namedview_uids={'shared': 'named-new'}))\n"
        "call insert_annotations.execute('C:/jobs/test.mdb', '7', [InsertAnnotationSpec(page_uid='p1', annotation_type='rect', position=[1.0, 1.0, 2.0, 2.0], color='#000000', width=1.0, properties={}, layer_uid='')], PasteRefRemap(takeoff_uids={'parent': 'p-new', 'hole': 'h-new'}, namedview_uids={'shared': 'named-new'}))\n"
        "request annotations_collection:7@7,conditions_collection:7@7,page:p1@7,takeoffs_collection:7@7 child=False editors=False type=plan_items_paste\n"
        "value {'takeoff_uids': {'parent': 'p-new', 'hole': 'h-new'}, 'annotation_uids': {'namedview/shared': 'named-new', 'rect/shared': 'rect-new'}, 'condition_uids': {'c1': 'c9'}}\n"
        "record annotation:namedview/named-new@7 create\n"
        "record annotation:rect/rect-new@7 create\n"
        "record annotations_collection:7@7 update\n"
        "record condition:c9@7 create\n"
        "record conditions_collection:7@7 update\n"
        "record takeoff:h-new@7 create\n"
        "record takeoff:p-new@7 create\n"
        "record takeoffs_collection:7@7 update\n"
        "reload C:/jobs/test.mdb\n"
        "event REFRESH\n"
    ),
}
_PLAN_QUEUE_EXPECTED = {
    "placement": (
        "request takeoff_placement surface=main-plan bid=7 page='20'\n"
        "resources takeoffs_collection:7@7\n"
        "dependencies area:5@7,condition:10@7,condition:11@7,page:20@7,page:21@7,takeoff:30@7\n"
        "payload (InsertTakeoffSpec(condition_uid='10', page_uid='20', area_uid='5', position=[1.0, 2.0], parent_uid='30', curve=-1, rotation=0.0, is_negative=False, raw_extras={}, source_bid_uid=None), InsertTakeoffSpec(condition_uid='11', page_uid='21', area_uid='0', position=[3.0, 4.0], parent_uid=None, curve=-1, rotation=0.0, is_negative=False, raw_extras={}, source_bid_uid=None))\n"
        "lease=False\n"
        "outcome committed\n"
        "executed area:5@7,condition:10@7,condition:11@7,page:20@7,page:21@7,takeoff:30@7,takeoffs_collection:7@7 child=False editors=False type=takeoff_placement id_ok=True hash_ok=True\n"
        "call insert_takeoffs.execute('C:/jobs/test.mdb', '7', [InsertTakeoffSpec(condition_uid='10', page_uid='20', area_uid='5', position=[1.0, 2.0], parent_uid='30', curve=-1, rotation=0.0, is_negative=False, raw_extras={}, source_bid_uid=None), InsertTakeoffSpec(condition_uid='11', page_uid='21', area_uid='0', position=[3.0, 4.0], parent_uid=None, curve=-1, rotation=0.0, is_negative=False, raw_extras={}, source_bid_uid=None)])\n"
        "value ['101', '102']\n"
        "record takeoff:101@7 create\n"
        "record takeoff:102@7 create\n"
        "record takeoffs_collection:7@7 update\n"
        "created=() maps=(('takeoffs', (('0', '101'), ('1', '102'))),)\n"
        "updated  deleted \n"
        "pages=('20', '21') conditions=('10', '11') families=('takeoffs',)\n"
    ),
    "delete mixed": (
        "request plan_items_delete surface=main-plan bid=7 page=''\n"
        "resources annotation:line/a2@7,annotation:rect/a1@7,takeoff:30@7,takeoff:31@7\n"
        "dependencies annotations_collection:7@7,condition:10@7,page:20@7,page:21@7,takeoffs_collection:7@7\n"
        "payload PlanItemsDeletePayload(takeoff_uids=('30', '31'), annotations=(('a1', 'rect'), ('a2', 'line')))\n"
        "lease=False\n"
        "outcome committed\n"
        "executed annotation:line/a2@7,annotation:rect/a1@7,annotations_collection:7@7,condition:10@7,page:20@7,page:21@7,takeoff:30@7,takeoff:31@7,takeoffs_collection:7@7 child=False editors=False type=plan_items_delete id_ok=True hash_ok=True\n"
        "verify ('C:/jobs/test.mdb', '7', ('30', '31'), (('a1', 'rect'), ('a2', 'line')), ())\n"
        "call delete_annotations.execute('C:/jobs/test.mdb', [('a1', 'rect'), ('a2', 'line')])\n"
        "call delete_takeoffs.execute('C:/jobs/test.mdb', ['30', '31'])\n"
        "value True\n"
        "record annotation:line/a2@7 delete\n"
        "record annotation:rect/a1@7 delete\n"
        "record annotations_collection:7@7 update\n"
        "record takeoff:30@7 delete\n"
        "record takeoff:31@7 delete\n"
        "record takeoffs_collection:7@7 update\n"
        "created=() maps=()\n"
        "updated  deleted annotation:line/a2@7,annotation:rect/a1@7,takeoff:30@7,takeoff:31@7\n"
        "pages=('20', '21') conditions=() families=('takeoffs', 'annotations')\n"
    ),
    "delete takeoffs only": (
        "request plan_items_delete surface=page-dialog bid=7 page='20'\n"
        "resources takeoff:30@7\n"
        "dependencies page:20@7,takeoffs_collection:7@7\n"
        "payload PlanItemsDeletePayload(takeoff_uids=('30',), annotations=())\n"
        "lease=False\n"
        "outcome committed\n"
        "executed page:20@7,takeoff:30@7,takeoffs_collection:7@7 child=False editors=False type=plan_items_delete id_ok=True hash_ok=True\n"
        "verify ('C:/jobs/test.mdb', '7', ('30',), (), ())\n"
        "call delete_takeoffs.execute('C:/jobs/test.mdb', ['30'])\n"
        "value True\n"
        "record takeoff:30@7 delete\n"
        "record takeoffs_collection:7@7 update\n"
        "created=() maps=()\n"
        "updated  deleted takeoff:30@7\n"
        "pages=('20',) conditions=() families=('takeoffs',)\n"
    ),
    "delete annotations only": (
        "request plan_items_delete surface=main-plan bid=7 page=''\n"
        "resources annotation:rect/a1@7\n"
        "dependencies annotations_collection:7@7\n"
        "payload PlanItemsDeletePayload(takeoff_uids=(), annotations=(('a1', 'rect'),))\n"
        "lease=False\n"
        "outcome committed\n"
        "executed annotation:rect/a1@7,annotations_collection:7@7 child=False editors=False type=plan_items_delete id_ok=True hash_ok=True\n"
        "verify ('C:/jobs/test.mdb', '7', (), (('a1', 'rect'),), ())\n"
        "call delete_annotations.execute('C:/jobs/test.mdb', [('a1', 'rect')])\n"
        "value True\n"
        "record annotation:rect/a1@7 delete\n"
        "record annotations_collection:7@7 update\n"
        "created=() maps=()\n"
        "updated  deleted annotation:rect/a1@7\n"
        "pages=() conditions=() families=('annotations',)\n"
    ),
    "geometry mixed": (
        "request plan_geometry surface=main-plan bid=7 page=''\n"
        "resources annotation:rect/a1@7,takeoff:30@7,takeoff:31@7,takeoff:32@7\n"
        "dependencies condition:10@7,page:20@7,page:21@7\n"
        "payload PlanGeometryPayload(takeoff_positions=(('30', (1.0, 2.0)), ('31', (3.5, 4.0))), takeoff_rotations=(('30', 90.0), ('32', 45.5)), annotation_positions=(('a1', 'rect', (1.0, 2.0, 3.0, 4.0)),))\n"
        "lease=False\n"
        "outcome committed\n"
        "executed annotation:rect/a1@7,condition:10@7,page:20@7,page:21@7,takeoff:30@7,takeoff:31@7,takeoff:32@7 child=False editors=False type=plan_geometry id_ok=True hash_ok=True\n"
        "verify ('C:/jobs/test.mdb', '7', ('30', '31', '32'), (('a1', 'rect'),), ())\n"
        "call save_takeoff_positions.execute('C:/jobs/test.mdb', [('30', [1.0, 2.0]), ('31', [3.5, 4.0])])\n"
        "call save_takeoff_rotations.execute('C:/jobs/test.mdb', [('30', 90.0), ('32', 45.5)])\n"
        "call save_annotation_positions.execute('C:/jobs/test.mdb', [('a1', 'rect', [1.0, 2.0, 3.0, 4.0])])\n"
        "value True\n"
        "record annotation:rect/a1@7 update fields=['position']\n"
        "record takeoff:30@7 update fields=['position', 'rotation']\n"
        "record takeoff:31@7 update fields=['position']\n"
        "record takeoff:32@7 update fields=['rotation']\n"
        "created=() maps=()\n"
        "updated annotation:rect/a1@7,takeoff:30@7,takeoff:31@7,takeoff:32@7 deleted \n"
        "pages=('20', '21') conditions=() families=('takeoffs', 'annotations')\n"
    ),
    "geometry rotation only": (
        "request plan_geometry surface=main-plan bid=7 page='21'\n"
        "resources takeoff:32@7\n"
        "dependencies page:21@7\n"
        "payload PlanGeometryPayload(takeoff_positions=(), takeoff_rotations=(('32', 45.0),), annotation_positions=())\n"
        "lease=False\n"
        "outcome committed\n"
        "executed page:21@7,takeoff:32@7 child=False editors=False type=plan_geometry id_ok=True hash_ok=True\n"
        "verify ('C:/jobs/test.mdb', '7', ('32',), (), ())\n"
        "call save_takeoff_rotations.execute('C:/jobs/test.mdb', [('32', 45.0)])\n"
        "value True\n"
        "record takeoff:32@7 update fields=['rotation']\n"
        "created=() maps=()\n"
        "updated takeoff:32@7 deleted \n"
        "pages=('21',) conditions=() families=('takeoffs',)\n"
    ),
    "geometry annotations only": (
        "request plan_geometry surface=main-plan bid=7 page=''\n"
        "resources annotation:line/a1@7\n"
        "dependencies \n"
        "payload PlanGeometryPayload(takeoff_positions=(), takeoff_rotations=(), annotation_positions=(('a1', 'line', (1.0, 2.0)),))\n"
        "lease=False\n"
        "outcome committed\n"
        "executed annotation:line/a1@7 child=False editors=False type=plan_geometry id_ok=True hash_ok=True\n"
        "verify ('C:/jobs/test.mdb', '7', (), (('a1', 'line'),), ())\n"
        "call save_annotation_positions.execute('C:/jobs/test.mdb', [('a1', 'line', [1.0, 2.0])])\n"
        "value True\n"
        "record annotation:line/a1@7 update fields=['position']\n"
        "created=() maps=()\n"
        "updated annotation:line/a1@7 deleted \n"
        "pages=() conditions=() families=('annotations',)\n"
    ),
    "properties takeoff_text": (
        "request takeoff_properties surface=main-plan bid=7 page='20'\n"
        "resources takeoff:30@7\n"
        "dependencies page:20@7,takeoff:30@7,takeoff:31@7\n"
        "payload PlanPropertyPayload(property_kind='takeoff_text', updates_json='[[\"30\",{\"Text\":\"T\"}]]', takeoff_ownership=(PlanTakeoffOwnership(uid='30', page_uid='20', condition_uid='10', area_uid='5', parent_uid='0'), PlanTakeoffOwnership(uid='31', page_uid='20', condition_uid='10', area_uid='0', parent_uid='30')))\n"
        "lease=False\n"
        "outcome committed\n"
        "executed page:20@7,takeoff:30@7,takeoff:31@7 child=False editors=False type=takeoff_properties id_ok=True hash_ok=True\n"
        "baseline page:20@7,takeoff:30@7,takeoff:31@7\n"
        "verify ('C:/jobs/test.mdb', '7', ('30', '31'), (), ('30', '31'))\n"
        "call save_takeoff_text_properties.execute('C:/jobs/test.mdb', [('30', {'Text': 'T'})])\n"
        "value True\n"
        "record takeoff:30@7 update fields=['text_properties']\n"
        "created=() maps=()\n"
        "updated takeoff:30@7 deleted \n"
        "pages=('20',) conditions=() families=('takeoffs',)\n"
    ),
    "properties takeoff_area": (
        "request takeoff_properties surface=main-plan bid=7 page=''\n"
        "resources takeoff:30@7,takeoff:31@7,takeoff:32@7\n"
        "dependencies condition:10@7,takeoff:30@7,takeoff:31@7,takeoff:32@7\n"
        "payload PlanPropertyPayload(property_kind='takeoff_area', updates_json='[[\"30\",\"5\"],[\"32\",\"0\"],[\"31\",\"5\"]]', takeoff_ownership=(PlanTakeoffOwnership(uid='30', page_uid='20', condition_uid='10', area_uid='5', parent_uid='0'), PlanTakeoffOwnership(uid='31', page_uid='20', condition_uid='10', area_uid='0', parent_uid='30'), PlanTakeoffOwnership(uid='32', page_uid='21', condition_uid='11', area_uid='0', parent_uid='0')))\n"
        "lease=False\n"
        "outcome committed\n"
        "executed condition:10@7,takeoff:30@7,takeoff:31@7,takeoff:32@7 child=False editors=False type=takeoff_properties id_ok=True hash_ok=True\n"
        "baseline condition:10@7,takeoff:30@7,takeoff:31@7,takeoff:32@7\n"
        "verify ('C:/jobs/test.mdb', '7', ('30', '31', '32'), (), ('30', '31', '32'))\n"
        "call save_takeoffs_area.execute('C:/jobs/test.mdb', ['30', '31'], '5')\n"
        "call save_takeoffs_area.execute('C:/jobs/test.mdb', ['32'], '0')\n"
        "value True\n"
        "record takeoff:30@7 update fields=['area']\n"
        "record takeoff:31@7 update fields=['area']\n"
        "record takeoff:32@7 update fields=['area']\n"
        "created=() maps=()\n"
        "updated takeoff:30@7,takeoff:31@7,takeoff:32@7 deleted \n"
        "pages=() conditions=() families=('takeoffs',)\n"
    ),
    "properties takeoff_condition": (
        "request takeoff_properties surface=main-plan bid=7 page=''\n"
        "resources takeoff:30@7,takeoff:32@7\n"
        "dependencies takeoff:30@7,takeoff:31@7,takeoff:32@7\n"
        "payload PlanPropertyPayload(property_kind='takeoff_condition', updates_json='[[\"30\",\"10\"],[\"32\",\"10\"]]', takeoff_ownership=(PlanTakeoffOwnership(uid='30', page_uid='20', condition_uid='10', area_uid='5', parent_uid='0'), PlanTakeoffOwnership(uid='31', page_uid='20', condition_uid='10', area_uid='0', parent_uid='30'), PlanTakeoffOwnership(uid='32', page_uid='21', condition_uid='11', area_uid='0', parent_uid='0')))\n"
        "lease=False\n"
        "outcome committed\n"
        "executed takeoff:30@7,takeoff:31@7,takeoff:32@7 child=False editors=False type=takeoff_properties id_ok=True hash_ok=True\n"
        "baseline takeoff:30@7,takeoff:31@7,takeoff:32@7\n"
        "verify ('C:/jobs/test.mdb', '7', ('30', '31', '32'), (), ('30', '31', '32'))\n"
        "call save_takeoffs_condition.execute('C:/jobs/test.mdb', ['30', '32'], '10')\n"
        "value True\n"
        "record takeoff:30@7 update fields=['condition']\n"
        "record takeoff:32@7 update fields=['condition']\n"
        "created=() maps=()\n"
        "updated takeoff:30@7,takeoff:32@7 deleted \n"
        "pages=() conditions=() families=('takeoffs',)\n"
    ),
    "properties takeoff_negative": (
        "request takeoff_properties surface=main-plan bid=7 page=''\n"
        "resources takeoff:30@7,takeoff:32@7\n"
        "dependencies takeoff:30@7,takeoff:31@7,takeoff:32@7\n"
        "payload PlanPropertyPayload(property_kind='takeoff_negative', updates_json='[[\"30\",true],[\"32\",false]]', takeoff_ownership=(PlanTakeoffOwnership(uid='30', page_uid='20', condition_uid='10', area_uid='5', parent_uid='0'), PlanTakeoffOwnership(uid='31', page_uid='20', condition_uid='10', area_uid='0', parent_uid='30'), PlanTakeoffOwnership(uid='32', page_uid='21', condition_uid='11', area_uid='0', parent_uid='0')))\n"
        "lease=False\n"
        "outcome committed\n"
        "executed takeoff:30@7,takeoff:31@7,takeoff:32@7 child=False editors=False type=takeoff_properties id_ok=True hash_ok=True\n"
        "baseline takeoff:30@7,takeoff:31@7,takeoff:32@7\n"
        "verify ('C:/jobs/test.mdb', '7', ('30', '31', '32'), (), ('30', '31', '32'))\n"
        "call set_takeoffs_negative.execute('C:/jobs/test.mdb', ['30'], True)\n"
        "call set_takeoffs_negative.execute('C:/jobs/test.mdb', ['32'], False)\n"
        "value True\n"
        "record takeoff:30@7 update fields=['negative']\n"
        "record takeoff:32@7 update fields=['negative']\n"
        "created=() maps=()\n"
        "updated takeoff:30@7,takeoff:32@7 deleted \n"
        "pages=() conditions=() families=('takeoffs',)\n"
    ),
    "properties takeoff_curve": (
        "request takeoff_properties surface=main-plan bid=7 page=''\n"
        "resources takeoff:30@7\n"
        "dependencies page:20@7,page:21@7,takeoff:30@7,takeoff:31@7\n"
        "payload PlanPropertyPayload(property_kind='takeoff_curve', updates_json='[[\"30\",[1,2],3]]', takeoff_ownership=(PlanTakeoffOwnership(uid='30', page_uid='20', condition_uid='10', area_uid='5', parent_uid='0'), PlanTakeoffOwnership(uid='31', page_uid='20', condition_uid='10', area_uid='0', parent_uid='30')))\n"
        "lease=False\n"
        "outcome committed\n"
        "executed page:20@7,page:21@7,takeoff:30@7,takeoff:31@7 child=False editors=False type=takeoff_properties id_ok=True hash_ok=True\n"
        "baseline page:20@7,page:21@7,takeoff:30@7,takeoff:31@7\n"
        "verify ('C:/jobs/test.mdb', '7', ('30', '31'), (), ('30', '31'))\n"
        "call set_takeoff_curve.execute('C:/jobs/test.mdb', '30', [1.0, 2.0], 3)\n"
        "value True\n"
        "record takeoff:30@7 update fields=['position', 'curve']\n"
        "created=() maps=()\n"
        "updated takeoff:30@7 deleted \n"
        "pages=('20', '21') conditions=() families=('takeoffs',)\n"
    ),
    "properties annotation_text": (
        "request annotation_update surface=main-plan bid=7 page=''\n"
        "resources annotation:rect/a1@7\n"
        "dependencies \n"
        'payload PlanPropertyPayload(property_kind=\'annotation_text\', updates_json=\'[["a1","rect",{"Text":"T"}]]\', takeoff_ownership=())\n'
        "lease=False\n"
        "outcome committed\n"
        "executed annotation:rect/a1@7 child=False editors=False type=annotation_update id_ok=True hash_ok=True\n"
        "baseline annotation:rect/a1@7\n"
        "verify ('C:/jobs/test.mdb', '7', (), (('a1', 'rect'),), ())\n"
        "call save_annotation_text_properties.execute('C:/jobs/test.mdb', [('a1', 'rect', {'Text': 'T'})])\n"
        "value True\n"
        "record annotation:rect/a1@7 update fields=['text_properties']\n"
        "created=() maps=()\n"
        "updated annotation:rect/a1@7 deleted \n"
        "pages=() conditions=() families=('annotations',)\n"
    ),
    "properties annotation_style": (
        "request annotation_update surface=main-plan bid=7 page=''\n"
        "resources annotation:rect/a1@7\n"
        "dependencies \n"
        'payload PlanPropertyPayload(property_kind=\'annotation_style\', updates_json=\'[["a1","rect",{"color":"#112233"}]]\', takeoff_ownership=())\n'
        "lease=False\n"
        "outcome committed\n"
        "executed annotation:rect/a1@7 child=False editors=False type=annotation_update id_ok=True hash_ok=True\n"
        "baseline annotation:rect/a1@7\n"
        "verify ('C:/jobs/test.mdb', '7', (), (('a1', 'rect'),), ())\n"
        "call save_annotation_styles.execute('C:/jobs/test.mdb', [('a1', 'rect', {'color': '#112233'})])\n"
        "value True\n"
        "record annotation:rect/a1@7 update fields=['style']\n"
        "created=() maps=()\n"
        "updated annotation:rect/a1@7 deleted \n"
        "pages=() conditions=() families=('annotations',)\n"
    ),
    "paste same bid": (
        "request plan_items_paste surface=main-plan bid=7 page='p1'\n"
        "resources annotations_collection:7@7,takeoffs_collection:7@7\n"
        "dependencies condition:c1@7,page:p1@7\n"
        "payload PlanItemsPastePayload(source_bid_uid='7', destination_bid_uid='7', takeoff_source_uids=('parent', 'hole'), takeoff_specs=(InsertTakeoffSpec(condition_uid='c1', page_uid='p1', area_uid='0', position=[0.0, 0.0, 10.0, 0.0], parent_uid='0', curve=-1, rotation=0.0, is_negative=False, raw_extras={}, source_bid_uid=None), InsertTakeoffSpec(condition_uid='c1', page_uid='p1', area_uid='0', position=[2.0, 2.0, 4.0, 2.0], parent_uid='parent', curve=-1, rotation=0.0, is_negative=True, raw_extras={}, source_bid_uid=None)), annotation_source_uids=('namedview/shared', 'rect/shared'), annotation_specs=(InsertAnnotationSpec(page_uid='p1', annotation_type='namedview', position=[0.0, 0.0, 1.0, 1.0], color='#000000', width=1.0, properties={}, layer_uid=''), InsertAnnotationSpec(page_uid='p1', annotation_type='rect', position=[1.0, 1.0, 2.0, 2.0], color='#000000', width=1.0, properties={}, layer_uid='')), takeoff_external_parent_sources=())\n"
        "lease=False\n"
        "outcome committed\n"
        "executed annotations_collection:7@7,condition:c1@7,page:p1@7,takeoffs_collection:7@7 child=False editors=False type=plan_items_paste id_ok=True hash_ok=True\n"
        "call insert_takeoffs.execute('C:/jobs/test.mdb', '7', [InsertTakeoffSpec(condition_uid='c1', page_uid='p1', area_uid='0', position=[0.0, 0.0, 10.0, 0.0], parent_uid='0', curve=-1, rotation=0.0, is_negative=False, raw_extras={}, source_bid_uid=None)])\n"
        "call insert_takeoffs.execute('C:/jobs/test.mdb', '7', [InsertTakeoffSpec(condition_uid='c1', page_uid='p1', area_uid='0', position=[2.0, 2.0, 4.0, 2.0], parent_uid='p-new', curve=-1, rotation=0.0, is_negative=True, raw_extras={}, source_bid_uid=None)])\n"
        "call insert_annotations.execute('C:/jobs/test.mdb', '7', [InsertAnnotationSpec(page_uid='p1', annotation_type='namedview', position=[0.0, 0.0, 1.0, 1.0], color='#000000', width=1.0, properties={}, layer_uid='')], PasteRefRemap(takeoff_uids={'parent': 'p-new', 'hole': 'h-new'}, namedview_uids={'shared': 'named-new'}))\n"
        "call insert_annotations.execute('C:/jobs/test.mdb', '7', [InsertAnnotationSpec(page_uid='p1', annotation_type='rect', position=[1.0, 1.0, 2.0, 2.0], color='#000000', width=1.0, properties={}, layer_uid='')], PasteRefRemap(takeoff_uids={'parent': 'p-new', 'hole': 'h-new'}, namedview_uids={'shared': 'named-new'}))\n"
        "value {'takeoff_uids': {'parent': 'p-new', 'hole': 'h-new'}, 'annotation_uids': {'namedview/shared': 'named-new', 'rect/shared': 'rect-new'}, 'condition_uids': {}}\n"
        "record annotation:namedview/named-new@7 create\n"
        "record annotation:rect/rect-new@7 create\n"
        "record annotations_collection:7@7 update\n"
        "record takeoff:h-new@7 create\n"
        "record takeoff:p-new@7 create\n"
        "record takeoffs_collection:7@7 update\n"
        "created=('p-new', 'h-new', 'named-new', 'rect-new') maps=(('takeoffs', (('hole', 'h-new'), ('parent', 'p-new'))), ('annotations', (('namedview/shared', 'named-new'), ('rect/shared', 'rect-new'))), ('conditions', ()))\n"
        "updated  deleted \n"
        "pages=('p1',) conditions=() families=('takeoffs', 'annotations')\n"
    ),
    "paste cross bid": (
        "request plan_items_paste surface=paste-dialog bid=7 page='p1'\n"
        "resources annotations_collection:7@7,conditions_collection:7@7,takeoffs_collection:7@7\n"
        "dependencies condition:10@7,page:p1@7\n"
        "payload PlanItemsPastePayload(source_bid_uid='6', destination_bid_uid='7', takeoff_source_uids=('parent', 'hole'), takeoff_specs=(InsertTakeoffSpec(condition_uid='c1', page_uid='p1', area_uid='0', position=[0.0, 0.0, 10.0, 0.0], parent_uid='0', curve=-1, rotation=0.0, is_negative=False, raw_extras={}, source_bid_uid=None), InsertTakeoffSpec(condition_uid='c1', page_uid='p1', area_uid='0', position=[2.0, 2.0, 4.0, 2.0], parent_uid='parent', curve=-1, rotation=0.0, is_negative=True, raw_extras={}, source_bid_uid=None)), annotation_source_uids=('namedview/shared', 'rect/shared'), annotation_specs=(InsertAnnotationSpec(page_uid='p1', annotation_type='namedview', position=[0.0, 0.0, 1.0, 1.0], color='#000000', width=1.0, properties={}, layer_uid=''), InsertAnnotationSpec(page_uid='p1', annotation_type='rect', position=[1.0, 1.0, 2.0, 2.0], color='#000000', width=1.0, properties={}, layer_uid='')), takeoff_external_parent_sources=())\n"
        "lease=False\n"
        "outcome committed\n"
        "executed annotations_collection:7@7,condition:10@7,conditions_collection:7@7,page:p1@7,takeoffs_collection:7@7 child=False editors=False type=plan_items_paste id_ok=True hash_ok=True\n"
        "call duplicate_conditions.execute_to_bid('C:/jobs/test.mdb', '6', '7', ['c1'])\n"
        "call insert_takeoffs.execute('C:/jobs/test.mdb', '7', [InsertTakeoffSpec(condition_uid='c9', page_uid='p1', area_uid='0', position=[0.0, 0.0, 10.0, 0.0], parent_uid='0', curve=-1, rotation=0.0, is_negative=False, raw_extras={}, source_bid_uid=None)])\n"
        "call insert_takeoffs.execute('C:/jobs/test.mdb', '7', [InsertTakeoffSpec(condition_uid='c9', page_uid='p1', area_uid='0', position=[2.0, 2.0, 4.0, 2.0], parent_uid='p-new', curve=-1, rotation=0.0, is_negative=True, raw_extras={}, source_bid_uid=None)])\n"
        "call insert_annotations.execute('C:/jobs/test.mdb', '7', [InsertAnnotationSpec(page_uid='p1', annotation_type='namedview', position=[0.0, 0.0, 1.0, 1.0], color='#000000', width=1.0, properties={}, layer_uid='')], PasteRefRemap(takeoff_uids={'parent': 'p-new', 'hole': 'h-new'}, namedview_uids={'shared': 'named-new'}))\n"
        "call insert_annotations.execute('C:/jobs/test.mdb', '7', [InsertAnnotationSpec(page_uid='p1', annotation_type='rect', position=[1.0, 1.0, 2.0, 2.0], color='#000000', width=1.0, properties={}, layer_uid='')], PasteRefRemap(takeoff_uids={'parent': 'p-new', 'hole': 'h-new'}, namedview_uids={'shared': 'named-new'}))\n"
        "value {'takeoff_uids': {'parent': 'p-new', 'hole': 'h-new'}, 'annotation_uids': {'namedview/shared': 'named-new', 'rect/shared': 'rect-new'}, 'condition_uids': {'c1': 'c9'}}\n"
        "record annotation:namedview/named-new@7 create\n"
        "record annotation:rect/rect-new@7 create\n"
        "record annotations_collection:7@7 update\n"
        "record condition:c9@7 create\n"
        "record conditions_collection:7@7 update\n"
        "record takeoff:h-new@7 create\n"
        "record takeoff:p-new@7 create\n"
        "record takeoffs_collection:7@7 update\n"
        "created=('p-new', 'h-new', 'named-new', 'rect-new') maps=(('takeoffs', (('hole', 'h-new'), ('parent', 'p-new'))), ('annotations', (('namedview/shared', 'named-new'), ('rect/shared', 'rect-new'))), ('conditions', (('c1', 'c9'),)))\n"
        "updated  deleted \n"
        "pages=('p1',) conditions=('c9',) families=('takeoffs', 'annotations')\n"
    ),
    "page scale": (
        "request page_settings surface=main-plan bid=7 page=''\n"
        "resources page:20@7,page:21@7\n"
        "dependencies \n"
        'payload PageSettingsPayload(setting_kind=\'scale\', updates_json=\'[["20",1,96.5],["21",1,96.5],["20",1,96.5]]\')\n'
        "lease=False\n"
        "outcome committed\n"
        "executed page:20@7,page:21@7 child=False editors=False type=page_settings id_ok=True hash_ok=True\n"
        "call save_page_scale.execute('C:/jobs/test.mdb', '20', 1.0, 96.5)\n"
        "call save_page_scale.execute('C:/jobs/test.mdb', '21', 1.0, 96.5)\n"
        "call save_page_scale.execute('C:/jobs/test.mdb', '20', 1.0, 96.5)\n"
        "value True\n"
        "record page:20@7 update fields=['scale']\n"
        "record page:21@7 update fields=['scale']\n"
        "created=() maps=()\n"
        "updated page:20@7,page:21@7 deleted \n"
        "pages=('20', '21') conditions=() families=('pages',)\n"
    ),
    "page show_mode": (
        "request page_settings surface=main-plan bid=7 page='20'\n"
        "resources page:20@7\n"
        "dependencies \n"
        "payload PageSettingsPayload(setting_kind='show_mode', updates_json='[[\"20\",2]]')\n"
        "lease=False\n"
        "outcome committed\n"
        "executed page:20@7 child=False editors=False type=page_settings id_ok=True hash_ok=True\n"
        "call save_page_show_mode.execute('C:/jobs/test.mdb', '20', 2)\n"
        "value True\n"
        "record page:20@7 update fields=['show_mode']\n"
        "created=() maps=()\n"
        "updated page:20@7 deleted \n"
        "pages=('20',) conditions=() families=('pages',)\n"
    ),
    "page overlay_image": (
        "request page_settings surface=main-plan bid=7 page='20'\n"
        "resources page:20@7\n"
        "dependencies \n"
        "payload PageSettingsPayload(setting_kind='overlay_image', updates_json='[[\"20\",\"C:/o.png\"]]')\n"
        "lease=False\n"
        "outcome committed\n"
        "executed page:20@7 child=False editors=False type=page_settings id_ok=True hash_ok=True\n"
        "call save_page_overlay_image.execute('C:/jobs/test.mdb', '20', 'C:/o.png')\n"
        "value True\n"
        "record page:20@7 update fields=['overlay_image']\n"
        "created=() maps=()\n"
        "updated page:20@7 deleted \n"
        "pages=('20',) conditions=() families=('pages',)\n"
    ),
    "page overlay_rect": (
        "request page_settings surface=main-plan bid=7 page='20'\n"
        "resources page:20@7\n"
        "dependencies \n"
        "payload PageSettingsPayload(setting_kind='overlay_rect', updates_json='[[\"20\",[1,2,3,4]]]')\n"
        "lease=False\n"
        "outcome committed\n"
        "executed page:20@7 child=False editors=False type=page_settings id_ok=True hash_ok=True\n"
        "call save_page_overlay_rect.execute('C:/jobs/test.mdb', '20', (1.0, 2.0, 3.0, 4.0))\n"
        "value True\n"
        "record page:20@7 update fields=['overlay_rect']\n"
        "created=() maps=()\n"
        "updated page:20@7 deleted \n"
        "pages=('20',) conditions=() families=('pages',)\n"
    ),
    "page invert": (
        "request page_settings surface=main-plan bid=7 page='20'\n"
        "resources page:20@7\n"
        "dependencies \n"
        "payload PageSettingsPayload(setting_kind='invert', updates_json='[[\"20\",1]]')\n"
        "lease=False\n"
        "outcome committed\n"
        "executed page:20@7 child=False editors=False type=page_settings id_ok=True hash_ok=True\n"
        "call save_page_invert.execute('C:/jobs/test.mdb', '20', True)\n"
        "value True\n"
        "record page:20@7 update fields=['invert']\n"
        "created=() maps=()\n"
        "updated page:20@7 deleted \n"
        "pages=('20',) conditions=() families=('pages',)\n"
    ),
    "page bitonal": (
        "request page_settings surface=main-plan bid=7 page='20'\n"
        "resources page:20@7\n"
        "dependencies \n"
        "payload PageSettingsPayload(setting_kind='bitonal', updates_json='[[\"20\",0]]')\n"
        "lease=False\n"
        "outcome committed\n"
        "executed page:20@7 child=False editors=False type=page_settings id_ok=True hash_ok=True\n"
        "call save_page_bitonal.execute('C:/jobs/test.mdb', '20', False)\n"
        "value True\n"
        "record page:20@7 update fields=['bitonal']\n"
        "created=() maps=()\n"
        "updated page:20@7 deleted \n"
        "pages=('20',) conditions=() families=('pages',)\n"
    ),
    "page image_adjustments": (
        "request page_settings surface=main-plan bid=7 page=''\n"
        "resources page:20@7,page:21@7\n"
        "dependencies \n"
        "payload PageSettingsPayload(setting_kind='image_adjustments', updates_json='[[\"20\",90,1,0,1,0],[\"21\",90,1,0,1,0]]')\n"
        "lease=False\n"
        "outcome committed\n"
        "executed page:20@7,page:21@7 child=False editors=False type=page_settings id_ok=True hash_ok=True\n"
        "call save_page_image_adjustments.execute('C:/jobs/test.mdb', ['20', '21'], 90, True, False, True, False)\n"
        "value True\n"
        "record page:20@7 update fields=['image_adjustments']\n"
        "record page:21@7 update fields=['image_adjustments']\n"
        "created=() maps=()\n"
        "updated page:20@7,page:21@7 deleted \n"
        "pages=('20', '21') conditions=() families=('pages',)\n"
    ),
    "page area": (
        "request page_settings surface=main-plan bid=7 page='20'\n"
        "resources page:20@7\n"
        "dependencies \n"
        "payload PageSettingsPayload(setting_kind='area', updates_json='[[\"20\",\"5\"]]')\n"
        "lease=False\n"
        "outcome committed\n"
        "executed page:20@7 child=False editors=False type=page_settings id_ok=True hash_ok=True\n"
        "call save_page_area.execute('C:/jobs/test.mdb', '20', '5')\n"
        "value True\n"
        "record page:20@7 update fields=['area']\n"
        "created=() maps=()\n"
        "updated page:20@7 deleted \n"
        "pages=('20',) conditions=() families=('pages',)\n"
    ),
    "page name": (
        "request page_settings surface=rename-dialog bid=7 page='20'\n"
        "resources page:20@7\n"
        "dependencies \n"
        "payload PageSettingsPayload(setting_kind='name', updates_json='[[\"20\",\"Sheet\"]]')\n"
        "lease=False\n"
        "outcome committed\n"
        "executed page:20@7 child=False editors=False type=page_settings id_ok=True hash_ok=True\n"
        "call save_page_name.execute('C:/jobs/test.mdb', '20', 'Sheet')\n"
        "value True\n"
        "record page:20@7 update fields=['name']\n"
        "created=() maps=()\n"
        "updated page:20@7 deleted \n"
        "pages=('20',) conditions=() families=('pages',)\n"
    ),
    "page layer_show": (
        "request page_settings surface=main-plan bid=7 page=''\n"
        "resources layer:40@7,layer:41@7\n"
        "dependencies \n"
        "payload PageSettingsPayload(setting_kind='layer_show', updates_json='[[\"40\",0],[\"41\",1]]')\n"
        "lease=False\n"
        "outcome committed\n"
        "executed layer:40@7,layer:41@7 child=False editors=False type=page_settings id_ok=True hash_ok=True\n"
        "call update_layer_show.execute('C:/jobs/test.mdb', '40', False)\n"
        "call update_layer_show.execute('C:/jobs/test.mdb', '41', True)\n"
        "value True\n"
        "record layer:40@7 update fields=['layer_show']\n"
        "record layer:41@7 update fields=['layer_show']\n"
        "created=() maps=()\n"
        "updated layer:40@7,layer:41@7 deleted \n"
        "pages=() conditions=() families=('layers',)\n"
    ),
}
_LOCAL_SCENARIO_EXPECTED = {
    "delete_bids|failure": (
        "False | "
        "calls=1 requests=['bid:7@7,bid:8@8'] records=0 values=[False] verify=0 reloads=0 events=[]"
    ),
    "delete_bids|denied": (
        "False | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "delete_bids|locked": (
        "True | "
        "calls=1 requests=['bid:7@7,bid:8@8'] records=2 values=[True] verify=0 reloads=1 events=['DatabaseRefreshedEvent']"
    ),
    "delete_bids|conflict": (
        "False | "
        "calls=0 requests=['bid:7@7,bid:8@8'] records=0 values=[None] verify=0 reloads=0 events=['SynchronizationConflictEvent']"
    ),
    "delete_bids|unknown": (
        "False | "
        "calls=1 requests=['bid:7@7,bid:8@8'] records=2 values=[None] verify=0 reloads=0 events=[]"
    ),
    "delete_bids|reload_failed": (
        "False | "
        "calls=1 requests=['bid:7@7,bid:8@8'] records=2 values=[True] verify=0 reloads=1 events=[]"
    ),
    "delete_bids|other_database": (
        "True | "
        "calls=1 requests=['bid:7@7,bid:8@8'] records=2 values=[True] verify=0 reloads=1 events=['DatabaseRefreshedEvent']"
    ),
    "delete_bids|equivalent_path": (
        "True | "
        "calls=1 requests=['bid:7@7,bid:8@8'] records=2 values=[True] verify=0 reloads=1 events=['DatabaseRefreshedEvent']"
    ),
    "delete_bids without refresh|failure": (
        "False | "
        "calls=1 requests=['bid:7@7'] records=0 values=[False] verify=0 reloads=0 events=[]"
    ),
    "delete_bids without refresh|denied": (
        "False | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "delete_bids without refresh|locked": (
        "True | "
        "calls=1 requests=['bid:7@7'] records=1 values=[True] verify=0 reloads=0 events=[]"
    ),
    "delete_bids without refresh|conflict": (
        "False | "
        "calls=0 requests=['bid:7@7'] records=0 values=[None] verify=0 reloads=0 events=['SynchronizationConflictEvent']"
    ),
    "delete_bids without refresh|unknown": (
        "False | "
        "calls=1 requests=['bid:7@7'] records=1 values=[None] verify=0 reloads=0 events=[]"
    ),
    "delete_bids without refresh|reload_failed": (
        "True | "
        "calls=1 requests=['bid:7@7'] records=1 values=[True] verify=0 reloads=0 events=[]"
    ),
    "delete_bids without refresh|other_database": (
        "True | "
        "calls=1 requests=['bid:7@7'] records=1 values=[True] verify=0 reloads=0 events=[]"
    ),
    "delete_bids without refresh|equivalent_path": (
        "True | "
        "calls=1 requests=['bid:7@7'] records=1 values=[True] verify=0 reloads=0 events=[]"
    ),
    "delete_bids empty|failure": ("no use case is reached"),
    "delete_bids empty|denied": (
        "True | " "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "delete_bids empty|locked": (
        "True | " "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "delete_bids empty|conflict": (
        "True | " "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "delete_bids empty|unknown": (
        "True | " "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "delete_bids empty|reload_failed": (
        "True | " "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "delete_bids empty|other_database": (
        "True | " "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "delete_bids empty|equivalent_path": (
        "True | " "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "delete_projects|failure": (
        "False | "
        "calls=1 requests=['project:3@None,project:4@None,bid:31@31,bid:41@41,projects_collection:database@None'] records=0 values=[False] verify=0 reloads=0 events=[]"
    ),
    "delete_projects|denied": (
        "False | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "delete_projects|locked": (
        "True | "
        "calls=1 requests=['project:3@None,project:4@None,bid:31@31,bid:41@41,projects_collection:database@None'] records=5 values=[True] verify=0 reloads=1 events=['DatabaseRefreshedEvent']"
    ),
    "delete_projects|conflict": (
        "False | "
        "calls=0 requests=['project:3@None,project:4@None,bid:31@31,bid:41@41,projects_collection:database@None'] records=0 values=[None] verify=0 reloads=0 events=['SynchronizationConflictEvent']"
    ),
    "delete_projects|unknown": (
        "False | "
        "calls=1 requests=['project:3@None,project:4@None,bid:31@31,bid:41@41,projects_collection:database@None'] records=5 values=[None] verify=0 reloads=0 events=[]"
    ),
    "delete_projects|reload_failed": (
        "False | "
        "calls=1 requests=['project:3@None,project:4@None,bid:31@31,bid:41@41,projects_collection:database@None'] records=5 values=[True] verify=0 reloads=1 events=[]"
    ),
    "delete_projects|other_database": (
        "True | "
        "calls=1 requests=['project:3@None,project:4@None,bid:31@31,bid:41@41,projects_collection:database@None'] records=5 values=[True] verify=0 reloads=1 events=['DatabaseRefreshedEvent']"
    ),
    "delete_projects|equivalent_path": (
        "True | "
        "calls=1 requests=['project:3@None,project:4@None,bid:31@31,bid:41@41,projects_collection:database@None'] records=5 values=[True] verify=0 reloads=1 events=['DatabaseRefreshedEvent']"
    ),
    "create_project_result|failure": (
        "WriteReloadResult(value=None, write_success=False, reload_success=False, failure_reason=None, blocked_uids=[]) | "
        "calls=1 requests=['projects_collection:database@None'] records=0 values=[None] verify=0 reloads=0 events=[]"
    ),
    "create_project_result|denied": (
        "WriteReloadResult(value=None, write_success=False, reload_success=False, failure_reason=None, blocked_uids=[]) | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "create_project_result|locked": (
        "WriteReloadResult(value='9', write_success=True, reload_success=True, failure_reason=None, blocked_uids=[]) | "
        "calls=1 requests=['projects_collection:database@None'] records=2 values=['9'] verify=0 reloads=1 events=['DatabaseRefreshedEvent']"
    ),
    "create_project_result|conflict": (
        "WriteReloadResult(value=None, write_success=False, reload_success=False, failure_reason=None, blocked_uids=[]) | "
        "calls=0 requests=['projects_collection:database@None'] records=0 values=[None] verify=0 reloads=0 events=['SynchronizationConflictEvent']"
    ),
    "create_project_result|unknown": (
        "WriteReloadResult(value=None, write_success=False, reload_success=False, failure_reason=None, blocked_uids=[]) | "
        "calls=1 requests=['projects_collection:database@None'] records=2 values=[None] verify=0 reloads=0 events=[]"
    ),
    "create_project_result|reload_failed": (
        "WriteReloadResult(value='9', write_success=True, reload_success=False, failure_reason=None, blocked_uids=[]) | "
        "calls=1 requests=['projects_collection:database@None'] records=2 values=['9'] verify=0 reloads=1 events=[]"
    ),
    "create_project_result|other_database": (
        "WriteReloadResult(value='9', write_success=True, reload_success=True, failure_reason=None, blocked_uids=[]) | "
        "calls=1 requests=['projects_collection:database@None'] records=2 values=['9'] verify=0 reloads=1 events=['DatabaseRefreshedEvent']"
    ),
    "create_project_result|equivalent_path": (
        "WriteReloadResult(value='9', write_success=True, reload_success=True, failure_reason=None, blocked_uids=[]) | "
        "calls=1 requests=['projects_collection:database@None'] records=2 values=['9'] verify=0 reloads=1 events=['DatabaseRefreshedEvent']"
    ),
    "rename_project|failure": (
        "False | "
        "calls=1 requests=['project:3@None'] records=0 values=[False] verify=0 reloads=0 events=[]"
    ),
    "rename_project|denied": (
        "False | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "rename_project|locked": (
        "True | "
        "calls=1 requests=['project:3@None'] records=1 values=[True] verify=0 reloads=1 events=['DatabaseRefreshedEvent']"
    ),
    "rename_project|conflict": (
        "False | "
        "calls=0 requests=['project:3@None'] records=0 values=[None] verify=0 reloads=0 events=['SynchronizationConflictEvent']"
    ),
    "rename_project|unknown": (
        "False | "
        "calls=1 requests=['project:3@None'] records=1 values=[None] verify=0 reloads=0 events=[]"
    ),
    "rename_project|reload_failed": (
        "False | "
        "calls=1 requests=['project:3@None'] records=1 values=[True] verify=0 reloads=1 events=[]"
    ),
    "rename_project|other_database": (
        "True | "
        "calls=1 requests=['project:3@None'] records=1 values=[True] verify=0 reloads=1 events=['DatabaseRefreshedEvent']"
    ),
    "rename_project|equivalent_path": (
        "True | "
        "calls=1 requests=['project:3@None'] records=1 values=[True] verify=0 reloads=1 events=['DatabaseRefreshedEvent']"
    ),
    "move_bids|failure": (
        "False | "
        "calls=1 requests=['bid:7@7,bid:8@8,project_bids:3@None,project_bids:4@None'] records=0 values=[False] verify=0 reloads=0 events=[]"
    ),
    "move_bids|denied": (
        "False | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "move_bids|locked": (
        "False | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "move_bids|conflict": (
        "False | "
        "calls=0 requests=['bid:7@7,bid:8@8,project_bids:3@None,project_bids:4@None'] records=0 values=[None] verify=0 reloads=0 events=['SynchronizationConflictEvent']"
    ),
    "move_bids|unknown": (
        "False | "
        "calls=1 requests=['bid:7@7,bid:8@8,project_bids:3@None,project_bids:4@None'] records=4 values=[None] verify=0 reloads=0 events=[]"
    ),
    "move_bids|reload_failed": (
        "False | "
        "calls=1 requests=['bid:7@7,bid:8@8,project_bids:3@None,project_bids:4@None'] records=4 values=[True] verify=0 reloads=1 events=[]"
    ),
    "move_bids|other_database": (
        "True | "
        "calls=1 requests=['bid:7@7,bid:8@8,project_bids:3@None,project_bids:4@None'] records=4 values=[True] verify=0 reloads=1 events=['DatabaseRefreshedEvent']"
    ),
    "move_bids|equivalent_path": (
        "True | "
        "calls=1 requests=['bid:7@7,bid:8@8,project_bids:3@None,project_bids:4@None'] records=4 values=[True] verify=0 reloads=1 events=['DatabaseRefreshedEvent']"
    ),
    "move_bids to orphan|failure": (
        "False | "
        "calls=1 requests=['bid:7@7,project_bids:orphan@None'] records=0 values=[False] verify=0 reloads=0 events=[]"
    ),
    "move_bids to orphan|denied": (
        "False | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "move_bids to orphan|locked": (
        "False | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "move_bids to orphan|conflict": (
        "False | "
        "calls=0 requests=['bid:7@7,project_bids:orphan@None'] records=0 values=[None] verify=0 reloads=0 events=['SynchronizationConflictEvent']"
    ),
    "move_bids to orphan|unknown": (
        "False | "
        "calls=1 requests=['bid:7@7,project_bids:orphan@None'] records=2 values=[None] verify=0 reloads=0 events=[]"
    ),
    "move_bids to orphan|reload_failed": (
        "True | "
        "calls=1 requests=['bid:7@7,project_bids:orphan@None'] records=2 values=[True] verify=0 reloads=0 events=[]"
    ),
    "move_bids to orphan|other_database": (
        "True | "
        "calls=1 requests=['bid:7@7,project_bids:orphan@None'] records=2 values=[True] verify=0 reloads=0 events=[]"
    ),
    "move_bids to orphan|equivalent_path": (
        "True | "
        "calls=1 requests=['bid:7@7,project_bids:orphan@None'] records=2 values=[True] verify=0 reloads=0 events=[]"
    ),
    "duplicate_bid_result|failure": (
        "WriteReloadResult(value=None, write_success=False, reload_success=False, failure_reason=None, blocked_uids=[]) | "
        "calls=1 requests=['bid:7@7'] records=0 values=[None] verify=0 reloads=0 events=[]"
    ),
    "duplicate_bid_result|denied": (
        "WriteReloadResult(value=None, write_success=False, reload_success=False, failure_reason=None, blocked_uids=[]) | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "duplicate_bid_result|locked": (
        "WriteReloadResult(value='12', write_success=True, reload_success=True, failure_reason=None, blocked_uids=[]) | "
        "calls=1 requests=['bid:7@7'] records=1 values=['12'] verify=0 reloads=1 events=['DatabaseRefreshedEvent']"
    ),
    "duplicate_bid_result|conflict": (
        "WriteReloadResult(value=None, write_success=False, reload_success=False, failure_reason=None, blocked_uids=[]) | "
        "calls=0 requests=['bid:7@7'] records=0 values=[None] verify=0 reloads=0 events=['SynchronizationConflictEvent']"
    ),
    "duplicate_bid_result|unknown": (
        "WriteReloadResult(value=None, write_success=False, reload_success=False, failure_reason=None, blocked_uids=[]) | "
        "calls=1 requests=['bid:7@7'] records=1 values=[None] verify=0 reloads=0 events=[]"
    ),
    "duplicate_bid_result|reload_failed": (
        "WriteReloadResult(value='12', write_success=True, reload_success=False, failure_reason=None, blocked_uids=[]) | "
        "calls=1 requests=['bid:7@7'] records=1 values=['12'] verify=0 reloads=1 events=[]"
    ),
    "duplicate_bid_result|other_database": (
        "WriteReloadResult(value='12', write_success=True, reload_success=True, failure_reason=None, blocked_uids=[]) | "
        "calls=1 requests=['bid:7@7'] records=1 values=['12'] verify=0 reloads=1 events=['DatabaseRefreshedEvent']"
    ),
    "duplicate_bid_result|equivalent_path": (
        "WriteReloadResult(value='12', write_success=True, reload_success=True, failure_reason=None, blocked_uids=[]) | "
        "calls=1 requests=['bid:7@7'] records=1 values=['12'] verify=0 reloads=1 events=['DatabaseRefreshedEvent']"
    ),
    "duplicate_bid_result without reload|failure": (
        "WriteReloadResult(value=None, write_success=False, reload_success=False, failure_reason=None, blocked_uids=[]) | "
        "calls=1 requests=['bid:7@7'] records=0 values=[None] verify=0 reloads=0 events=[]"
    ),
    "duplicate_bid_result without reload|denied": (
        "WriteReloadResult(value=None, write_success=False, reload_success=False, failure_reason=None, blocked_uids=[]) | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "duplicate_bid_result without reload|locked": (
        "WriteReloadResult(value='12', write_success=True, reload_success=True, failure_reason=None, blocked_uids=[]) | "
        "calls=1 requests=['bid:7@7'] records=1 values=['12'] verify=0 reloads=0 events=[]"
    ),
    "duplicate_bid_result without reload|conflict": (
        "WriteReloadResult(value=None, write_success=False, reload_success=False, failure_reason=None, blocked_uids=[]) | "
        "calls=0 requests=['bid:7@7'] records=0 values=[None] verify=0 reloads=0 events=['SynchronizationConflictEvent']"
    ),
    "duplicate_bid_result without reload|unknown": (
        "WriteReloadResult(value=None, write_success=False, reload_success=False, failure_reason=None, blocked_uids=[]) | "
        "calls=1 requests=['bid:7@7'] records=1 values=[None] verify=0 reloads=0 events=[]"
    ),
    "duplicate_bid_result without reload|reload_failed": (
        "WriteReloadResult(value='12', write_success=True, reload_success=True, failure_reason=None, blocked_uids=[]) | "
        "calls=1 requests=['bid:7@7'] records=1 values=['12'] verify=0 reloads=0 events=[]"
    ),
    "duplicate_bid_result without reload|other_database": (
        "WriteReloadResult(value='12', write_success=True, reload_success=True, failure_reason=None, blocked_uids=[]) | "
        "calls=1 requests=['bid:7@7'] records=1 values=['12'] verify=0 reloads=0 events=[]"
    ),
    "duplicate_bid_result without reload|equivalent_path": (
        "WriteReloadResult(value='12', write_success=True, reload_success=True, failure_reason=None, blocked_uids=[]) | "
        "calls=1 requests=['bid:7@7'] records=1 values=['12'] verify=0 reloads=0 events=[]"
    ),
    "create_bid_result|failure": (
        "WriteReloadResult(value=None, write_success=False, reload_success=False, failure_reason=None, blocked_uids=[]) | "
        "calls=1 requests=['project_bids:3@None'] records=0 values=[None] verify=0 reloads=0 events=[]"
    ),
    "create_bid_result|denied": (
        "WriteReloadResult(value=None, write_success=False, reload_success=False, failure_reason=None, blocked_uids=[]) | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "create_bid_result|locked": (
        "WriteReloadResult(value='13', write_success=True, reload_success=True, failure_reason=None, blocked_uids=[]) | "
        "calls=1 requests=['project_bids:3@None'] records=2 values=['13'] verify=0 reloads=1 events=['DatabaseRefreshedEvent']"
    ),
    "create_bid_result|conflict": (
        "WriteReloadResult(value=None, write_success=False, reload_success=False, failure_reason=None, blocked_uids=[]) | "
        "calls=0 requests=['project_bids:3@None'] records=0 values=[None] verify=0 reloads=0 events=['SynchronizationConflictEvent']"
    ),
    "create_bid_result|unknown": (
        "WriteReloadResult(value=None, write_success=False, reload_success=False, failure_reason=None, blocked_uids=[]) | "
        "calls=1 requests=['project_bids:3@None'] records=2 values=[None] verify=0 reloads=0 events=[]"
    ),
    "create_bid_result|reload_failed": (
        "WriteReloadResult(value='13', write_success=True, reload_success=False, failure_reason=None, blocked_uids=[]) | "
        "calls=1 requests=['project_bids:3@None'] records=2 values=['13'] verify=0 reloads=1 events=[]"
    ),
    "create_bid_result|other_database": (
        "WriteReloadResult(value='13', write_success=True, reload_success=True, failure_reason=None, blocked_uids=[]) | "
        "calls=1 requests=['project_bids:3@None'] records=2 values=['13'] verify=0 reloads=1 events=['DatabaseRefreshedEvent']"
    ),
    "create_bid_result|equivalent_path": (
        "WriteReloadResult(value='13', write_success=True, reload_success=True, failure_reason=None, blocked_uids=[]) | "
        "calls=1 requests=['project_bids:3@None'] records=2 values=['13'] verify=0 reloads=1 events=['DatabaseRefreshedEvent']"
    ),
    "create_bid_result orphan|failure": (
        "WriteReloadResult(value=None, write_success=False, reload_success=False, failure_reason=None, blocked_uids=[]) | "
        "calls=1 requests=['project_bids:orphan@None'] records=0 values=[None] verify=0 reloads=0 events=[]"
    ),
    "create_bid_result orphan|denied": (
        "WriteReloadResult(value=None, write_success=False, reload_success=False, failure_reason=None, blocked_uids=[]) | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "create_bid_result orphan|locked": (
        "WriteReloadResult(value='13', write_success=True, reload_success=True, failure_reason=None, blocked_uids=[]) | "
        "calls=1 requests=['project_bids:orphan@None'] records=2 values=['13'] verify=0 reloads=1 events=['DatabaseRefreshedEvent']"
    ),
    "create_bid_result orphan|conflict": (
        "WriteReloadResult(value=None, write_success=False, reload_success=False, failure_reason=None, blocked_uids=[]) | "
        "calls=0 requests=['project_bids:orphan@None'] records=0 values=[None] verify=0 reloads=0 events=['SynchronizationConflictEvent']"
    ),
    "create_bid_result orphan|unknown": (
        "WriteReloadResult(value=None, write_success=False, reload_success=False, failure_reason=None, blocked_uids=[]) | "
        "calls=1 requests=['project_bids:orphan@None'] records=2 values=[None] verify=0 reloads=0 events=[]"
    ),
    "create_bid_result orphan|reload_failed": (
        "WriteReloadResult(value='13', write_success=True, reload_success=False, failure_reason=None, blocked_uids=[]) | "
        "calls=1 requests=['project_bids:orphan@None'] records=2 values=['13'] verify=0 reloads=1 events=[]"
    ),
    "create_bid_result orphan|other_database": (
        "WriteReloadResult(value='13', write_success=True, reload_success=True, failure_reason=None, blocked_uids=[]) | "
        "calls=1 requests=['project_bids:orphan@None'] records=2 values=['13'] verify=0 reloads=1 events=['DatabaseRefreshedEvent']"
    ),
    "create_bid_result orphan|equivalent_path": (
        "WriteReloadResult(value='13', write_success=True, reload_success=True, failure_reason=None, blocked_uids=[]) | "
        "calls=1 requests=['project_bids:orphan@None'] records=2 values=['13'] verify=0 reloads=1 events=['DatabaseRefreshedEvent']"
    ),
    "delete_conditions|failure": (
        "False | "
        "calls=1 requests=['conditions_collection:7@7'] records=0 values=[False] verify=0 reloads=0 events=[]"
    ),
    "delete_conditions|denied": (
        "False | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "delete_conditions|locked": (
        "False | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "delete_conditions|conflict": (
        "False | "
        "calls=0 requests=['conditions_collection:7@7'] records=0 values=[None] verify=0 reloads=0 events=['SynchronizationConflictEvent']"
    ),
    "delete_conditions|unknown": (
        "False | "
        "calls=1 requests=['conditions_collection:7@7'] records=3 values=[None] verify=0 reloads=0 events=[]"
    ),
    "delete_conditions|reload_failed": (
        "False | "
        "calls=1 requests=['conditions_collection:7@7'] records=3 values=[True] verify=0 reloads=1 events=[]"
    ),
    "delete_conditions|other_database": (
        "True | "
        "calls=1 requests=['conditions_collection:7@7'] records=3 values=[True] verify=0 reloads=1 events=['ConditionsChangedEvent']"
    ),
    "delete_conditions|equivalent_path": (
        "True | "
        "calls=1 requests=['conditions_collection:7@7'] records=3 values=[True] verify=0 reloads=1 events=['ConditionsChangedEvent']"
    ),
    "create_condition_folder_result|failure": (
        "WriteReloadResult(value=None, write_success=False, reload_success=False, failure_reason=None, blocked_uids=[]) | "
        "calls=1 requests=['conditions_collection:7@7'] records=0 values=[None] verify=0 reloads=0 events=[]"
    ),
    "create_condition_folder_result|denied": (
        "WriteReloadResult(value=None, write_success=False, reload_success=False, failure_reason=None, blocked_uids=[]) | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "create_condition_folder_result|locked": (
        "WriteReloadResult(value=None, write_success=False, reload_success=False, failure_reason=None, blocked_uids=[]) | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "create_condition_folder_result|conflict": (
        "WriteReloadResult(value=None, write_success=False, reload_success=False, failure_reason=None, blocked_uids=[]) | "
        "calls=0 requests=['conditions_collection:7@7'] records=0 values=[None] verify=0 reloads=0 events=['SynchronizationConflictEvent']"
    ),
    "create_condition_folder_result|unknown": (
        "WriteReloadResult(value=None, write_success=False, reload_success=False, failure_reason=None, blocked_uids=[]) | "
        "calls=1 requests=['conditions_collection:7@7'] records=2 values=[None] verify=0 reloads=0 events=[]"
    ),
    "create_condition_folder_result|reload_failed": (
        "WriteReloadResult(value='f9', write_success=True, reload_success=False, failure_reason=None, blocked_uids=[]) | "
        "calls=1 requests=['conditions_collection:7@7'] records=2 values=['f9'] verify=0 reloads=1 events=[]"
    ),
    "create_condition_folder_result|other_database": (
        "WriteReloadResult(value='f9', write_success=True, reload_success=True, failure_reason=None, blocked_uids=[]) | "
        "calls=1 requests=['conditions_collection:7@7'] records=2 values=['f9'] verify=0 reloads=1 events=['ConditionsChangedEvent']"
    ),
    "create_condition_folder_result|equivalent_path": (
        "WriteReloadResult(value='f9', write_success=True, reload_success=True, failure_reason=None, blocked_uids=[]) | "
        "calls=1 requests=['conditions_collection:7@7'] records=2 values=['f9'] verify=0 reloads=1 events=['ConditionsChangedEvent']"
    ),
    "rename_condition_folder|failure": (
        "False | "
        "calls=1 requests=['condition_folder:f1@7'] records=0 values=[False] verify=0 reloads=0 events=[]"
    ),
    "rename_condition_folder|denied": (
        "False | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "rename_condition_folder|locked": (
        "False | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "rename_condition_folder|conflict": (
        "False | "
        "calls=0 requests=['condition_folder:f1@7'] records=0 values=[None] verify=0 reloads=0 events=['SynchronizationConflictEvent']"
    ),
    "rename_condition_folder|unknown": (
        "False | "
        "calls=1 requests=['condition_folder:f1@7'] records=1 values=[None] verify=0 reloads=0 events=[]"
    ),
    "rename_condition_folder|reload_failed": (
        "False | "
        "calls=1 requests=['condition_folder:f1@7'] records=1 values=[True] verify=0 reloads=1 events=[]"
    ),
    "rename_condition_folder|other_database": (
        "True | "
        "calls=1 requests=['condition_folder:f1@7'] records=1 values=[True] verify=0 reloads=1 events=['ConditionsChangedEvent']"
    ),
    "rename_condition_folder|equivalent_path": (
        "True | "
        "calls=1 requests=['condition_folder:f1@7'] records=1 values=[True] verify=0 reloads=1 events=['ConditionsChangedEvent']"
    ),
    "duplicate_conditions_result|failure": (
        "WriteReloadResult(value=[], write_success=False, reload_success=False, failure_reason='The condition duplicate returned an incomplete identity map.', blocked_uids=[]) | "
        "calls=1 requests=['conditions_collection:7@7'] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "duplicate_conditions_result|denied": (
        "WriteReloadResult(value=[], write_success=False, reload_success=False, failure_reason=None, blocked_uids=[]) | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "duplicate_conditions_result|locked": (
        "WriteReloadResult(value=[], write_success=False, reload_success=False, failure_reason=None, blocked_uids=[]) | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "duplicate_conditions_result|conflict": (
        "WriteReloadResult(value=[], write_success=False, reload_success=False, failure_reason=None, blocked_uids=[]) | "
        "calls=0 requests=['conditions_collection:7@7'] records=0 values=[None] verify=0 reloads=0 events=['SynchronizationConflictEvent']"
    ),
    "duplicate_conditions_result|unknown": (
        "WriteReloadResult(value=[], write_success=False, reload_success=False, failure_reason=None, blocked_uids=[]) | "
        "calls=1 requests=['conditions_collection:7@7'] records=3 values=[None] verify=0 reloads=0 events=[]"
    ),
    "duplicate_conditions_result|reload_failed": (
        "WriteReloadResult(value=['c9', 'c10'], write_success=True, reload_success=False, failure_reason=None, blocked_uids=[]) | "
        "calls=1 requests=['conditions_collection:7@7'] records=3 values=[('c9', 'c10')] verify=0 reloads=1 events=[]"
    ),
    "duplicate_conditions_result|other_database": (
        "WriteReloadResult(value=['c9', 'c10'], write_success=True, reload_success=True, failure_reason=None, blocked_uids=[]) | "
        "calls=1 requests=['conditions_collection:7@7'] records=3 values=[('c9', 'c10')] verify=0 reloads=1 events=['ConditionsChangedEvent']"
    ),
    "duplicate_conditions_result|equivalent_path": (
        "WriteReloadResult(value=['c9', 'c10'], write_success=True, reload_success=True, failure_reason=None, blocked_uids=[]) | "
        "calls=1 requests=['conditions_collection:7@7'] records=3 values=[('c9', 'c10')] verify=0 reloads=1 events=['ConditionsChangedEvent']"
    ),
    "duplicate_conditions_to_bid|failure": (
        "{} | "
        "calls=1 requests=['conditions_collection:8@8'] records=0 values=[{}] verify=0 reloads=0 events=[]"
    ),
    "duplicate_conditions_to_bid|denied": (
        "{} | " "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "duplicate_conditions_to_bid|locked": (
        "{'c1': 'c9', 'c2': 'c10'} | "
        "calls=1 requests=['conditions_collection:8@8'] records=3 values=[{'c1': 'c9', 'c2': 'c10'}] verify=0 reloads=1 events=['ConditionsChangedEvent']"
    ),
    "duplicate_conditions_to_bid|conflict": (
        "{} | "
        "calls=0 requests=['conditions_collection:8@8'] records=0 values=[None] verify=0 reloads=0 events=['SynchronizationConflictEvent']"
    ),
    "duplicate_conditions_to_bid|unknown": (
        "{} | "
        "calls=1 requests=['conditions_collection:8@8'] records=3 values=[None] verify=0 reloads=0 events=[]"
    ),
    "duplicate_conditions_to_bid|reload_failed": (
        "{} | "
        "calls=1 requests=['conditions_collection:8@8'] records=3 values=[{'c1': 'c9', 'c2': 'c10'}] verify=0 reloads=1 events=[]"
    ),
    "duplicate_conditions_to_bid|other_database": (
        "{'c1': 'c9', 'c2': 'c10'} | "
        "calls=1 requests=['conditions_collection:8@8'] records=3 values=[{'c1': 'c9', 'c2': 'c10'}] verify=0 reloads=1 events=['ConditionsChangedEvent']"
    ),
    "duplicate_conditions_to_bid|equivalent_path": (
        "{'c1': 'c9', 'c2': 'c10'} | "
        "calls=1 requests=['conditions_collection:8@8'] records=3 values=[{'c1': 'c9', 'c2': 'c10'}] verify=0 reloads=1 events=['ConditionsChangedEvent']"
    ),
    "renumber_conditions|failure": (
        "False | "
        "calls=1 requests=['conditions_collection:7@7'] records=0 values=[False] verify=0 reloads=0 events=[]"
    ),
    "renumber_conditions|denied": (
        "False | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "renumber_conditions|locked": (
        "False | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "renumber_conditions|conflict": (
        "False | "
        "calls=0 requests=['conditions_collection:7@7'] records=0 values=[None] verify=0 reloads=0 events=['SynchronizationConflictEvent']"
    ),
    "renumber_conditions|unknown": (
        "False | "
        "calls=1 requests=['conditions_collection:7@7'] records=1 values=[None] verify=0 reloads=0 events=[]"
    ),
    "renumber_conditions|reload_failed": (
        "False | "
        "calls=1 requests=['conditions_collection:7@7'] records=1 values=[True] verify=0 reloads=1 events=[]"
    ),
    "renumber_conditions|other_database": (
        "True | "
        "calls=1 requests=['conditions_collection:7@7'] records=1 values=[True] verify=0 reloads=1 events=['ConditionsChangedEvent']"
    ),
    "renumber_conditions|equivalent_path": (
        "True | "
        "calls=1 requests=['conditions_collection:7@7'] records=1 values=[True] verify=0 reloads=1 events=['ConditionsChangedEvent']"
    ),
    "set_takeoff_curve|failure": (
        "False | "
        "calls=1 requests=['takeoff:30@7'] records=0 values=[False] verify=0 reloads=0 events=[]"
    ),
    "set_takeoff_curve|denied": (
        "False | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "set_takeoff_curve|locked": (
        "False | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "set_takeoff_curve|conflict": (
        "False | "
        "calls=0 requests=['takeoff:30@7'] records=0 values=[None] verify=0 reloads=0 events=['SynchronizationConflictEvent']"
    ),
    "set_takeoff_curve|unknown": (
        "False | "
        "calls=1 requests=['takeoff:30@7'] records=1 values=[None] verify=0 reloads=0 events=[]"
    ),
    "set_takeoff_curve|reload_failed": (
        "False | "
        "calls=1 requests=['takeoff:30@7'] records=1 values=[True] verify=0 reloads=1 events=[]"
    ),
    "set_takeoff_curve|other_database": (
        "True | "
        "calls=1 requests=['takeoff:30@None'] records=1 values=[True] verify=0 reloads=1 events=['DatabaseRefreshedEvent']"
    ),
    "set_takeoff_curve|equivalent_path": (
        "True | "
        "calls=1 requests=['takeoff:30@7'] records=1 values=[True] verify=0 reloads=1 events=['DatabaseRefreshedEvent']"
    ),
    "save_takeoff_positions|failure": (
        "False | "
        "calls=1 requests=['takeoff:30@7,takeoff:31@7'] records=0 values=[False] verify=0 reloads=0 events=[]"
    ),
    "save_takeoff_positions|denied": (
        "False | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "save_takeoff_positions|locked": (
        "False | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "save_takeoff_positions|conflict": (
        "False | "
        "calls=0 requests=['takeoff:30@7,takeoff:31@7'] records=0 values=[None] verify=0 reloads=0 events=['SynchronizationConflictEvent']"
    ),
    "save_takeoff_positions|unknown": (
        "False | "
        "calls=1 requests=['takeoff:30@7,takeoff:31@7'] records=2 values=[None] verify=0 reloads=0 events=[]"
    ),
    "save_takeoff_positions|reload_failed": (
        "False | "
        "calls=1 requests=['takeoff:30@7,takeoff:31@7'] records=2 values=[True] verify=0 reloads=1 events=[]"
    ),
    "save_takeoff_positions|other_database": (
        "True | "
        "calls=1 requests=['takeoff:30@None,takeoff:31@None'] records=2 values=[True] verify=0 reloads=1 events=['DatabaseRefreshedEvent']"
    ),
    "save_takeoff_positions|equivalent_path": (
        "True | "
        "calls=1 requests=['takeoff:30@7,takeoff:31@7'] records=2 values=[True] verify=0 reloads=1 events=['DatabaseRefreshedEvent']"
    ),
    "save_takeoff_rotations|failure": (
        "False | "
        "calls=1 requests=['takeoff:30@7'] records=0 values=[False] verify=0 reloads=0 events=[]"
    ),
    "save_takeoff_rotations|denied": (
        "False | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "save_takeoff_rotations|locked": (
        "False | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "save_takeoff_rotations|conflict": (
        "False | "
        "calls=0 requests=['takeoff:30@7'] records=0 values=[None] verify=0 reloads=0 events=['SynchronizationConflictEvent']"
    ),
    "save_takeoff_rotations|unknown": (
        "False | "
        "calls=1 requests=['takeoff:30@7'] records=1 values=[None] verify=0 reloads=0 events=[]"
    ),
    "save_takeoff_rotations|reload_failed": (
        "False | "
        "calls=1 requests=['takeoff:30@7'] records=1 values=[True] verify=0 reloads=1 events=[]"
    ),
    "save_takeoff_rotations|other_database": (
        "True | "
        "calls=1 requests=['takeoff:30@None'] records=1 values=[True] verify=0 reloads=1 events=['DatabaseRefreshedEvent']"
    ),
    "save_takeoff_rotations|equivalent_path": (
        "True | "
        "calls=1 requests=['takeoff:30@7'] records=1 values=[True] verify=0 reloads=1 events=['DatabaseRefreshedEvent']"
    ),
    "save_takeoff_text_properties|failure": (
        "False | "
        "calls=1 requests=['takeoff:30@7'] records=0 values=[False] verify=0 reloads=0 events=[]"
    ),
    "save_takeoff_text_properties|denied": (
        "False | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "save_takeoff_text_properties|locked": (
        "False | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "save_takeoff_text_properties|conflict": (
        "False | "
        "calls=0 requests=['takeoff:30@7'] records=0 values=[None] verify=0 reloads=0 events=['SynchronizationConflictEvent']"
    ),
    "save_takeoff_text_properties|unknown": (
        "False | "
        "calls=1 requests=['takeoff:30@7'] records=1 values=[None] verify=0 reloads=0 events=[]"
    ),
    "save_takeoff_text_properties|reload_failed": (
        "False | "
        "calls=1 requests=['takeoff:30@7'] records=1 values=[True] verify=0 reloads=1 events=[]"
    ),
    "save_takeoff_text_properties|other_database": (
        "True | "
        "calls=1 requests=['takeoff:30@None'] records=1 values=[True] verify=0 reloads=1 events=['DatabaseRefreshedEvent']"
    ),
    "save_takeoff_text_properties|equivalent_path": (
        "True | "
        "calls=1 requests=['takeoff:30@7'] records=1 values=[True] verify=0 reloads=1 events=['DatabaseRefreshedEvent']"
    ),
    "save_takeoffs_area|failure": (
        "False | "
        "calls=1 requests=['takeoff:30@7,takeoff:31@7'] records=0 values=[False] verify=0 reloads=0 events=[]"
    ),
    "save_takeoffs_area|denied": (
        "False | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "save_takeoffs_area|locked": (
        "False | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "save_takeoffs_area|conflict": (
        "False | "
        "calls=0 requests=['takeoff:30@7,takeoff:31@7'] records=0 values=[None] verify=0 reloads=0 events=['SynchronizationConflictEvent']"
    ),
    "save_takeoffs_area|unknown": (
        "False | "
        "calls=1 requests=['takeoff:30@7,takeoff:31@7'] records=2 values=[None] verify=0 reloads=0 events=[]"
    ),
    "save_takeoffs_area|reload_failed": (
        "False | "
        "calls=1 requests=['takeoff:30@7,takeoff:31@7'] records=2 values=[True] verify=0 reloads=1 events=[]"
    ),
    "save_takeoffs_area|other_database": (
        "True | "
        "calls=1 requests=['takeoff:30@None,takeoff:31@None'] records=2 values=[True] verify=0 reloads=1 events=['DatabaseRefreshedEvent']"
    ),
    "save_takeoffs_area|equivalent_path": (
        "True | "
        "calls=1 requests=['takeoff:30@7,takeoff:31@7'] records=2 values=[True] verify=0 reloads=1 events=['DatabaseRefreshedEvent']"
    ),
    "set_takeoffs_negative|failure": (
        "False | "
        "calls=1 requests=['takeoff:30@7,takeoff:31@7'] records=0 values=[False] verify=0 reloads=0 events=[]"
    ),
    "set_takeoffs_negative|denied": (
        "False | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "set_takeoffs_negative|locked": (
        "False | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "set_takeoffs_negative|conflict": (
        "False | "
        "calls=0 requests=['takeoff:30@7,takeoff:31@7'] records=0 values=[None] verify=0 reloads=0 events=['SynchronizationConflictEvent']"
    ),
    "set_takeoffs_negative|unknown": (
        "False | "
        "calls=1 requests=['takeoff:30@7,takeoff:31@7'] records=2 values=[None] verify=0 reloads=0 events=[]"
    ),
    "set_takeoffs_negative|reload_failed": (
        "False | "
        "calls=1 requests=['takeoff:30@7,takeoff:31@7'] records=2 values=[True] verify=0 reloads=1 events=[]"
    ),
    "set_takeoffs_negative|other_database": (
        "True | "
        "calls=1 requests=['takeoff:30@None,takeoff:31@None'] records=2 values=[True] verify=0 reloads=1 events=['DatabaseRefreshedEvent']"
    ),
    "set_takeoffs_negative|equivalent_path": (
        "True | "
        "calls=1 requests=['takeoff:30@7,takeoff:31@7'] records=2 values=[True] verify=0 reloads=1 events=['DatabaseRefreshedEvent']"
    ),
    "delete_takeoffs|failure": (
        "False | "
        "calls=1 requests=['takeoff:30@7,takeoff:31@7'] records=0 values=[False] verify=0 reloads=0 events=[]"
    ),
    "delete_takeoffs|denied": (
        "False | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "delete_takeoffs|locked": (
        "False | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "delete_takeoffs|conflict": (
        "False | "
        "calls=0 requests=['takeoff:30@7,takeoff:31@7'] records=0 values=[None] verify=0 reloads=0 events=['SynchronizationConflictEvent']"
    ),
    "delete_takeoffs|unknown": (
        "False | "
        "calls=1 requests=['takeoff:30@7,takeoff:31@7'] records=2 values=[None] verify=0 reloads=0 events=[]"
    ),
    "delete_takeoffs|reload_failed": (
        "False | "
        "calls=1 requests=['takeoff:30@7,takeoff:31@7'] records=2 values=[True] verify=0 reloads=1 events=[]"
    ),
    "delete_takeoffs|other_database": (
        "True | "
        "calls=1 requests=['takeoff:30@None,takeoff:31@None'] records=2 values=[True] verify=0 reloads=1 events=['DatabaseRefreshedEvent']"
    ),
    "delete_takeoffs|equivalent_path": (
        "True | "
        "calls=1 requests=['takeoff:30@7,takeoff:31@7'] records=2 values=[True] verify=0 reloads=1 events=['DatabaseRefreshedEvent']"
    ),
    "save_page_scale|failure": (
        "False | "
        "calls=1 requests=['page:20@7'] records=0 values=[False] verify=0 reloads=0 events=[]"
    ),
    "save_page_scale|denied": (
        "False | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "save_page_scale|locked": (
        "False | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "save_page_scale|conflict": (
        "False | "
        "calls=0 requests=['page:20@7'] records=0 values=[None] verify=0 reloads=0 events=['SynchronizationConflictEvent']"
    ),
    "save_page_scale|unknown": (
        "False | "
        "calls=1 requests=['page:20@7'] records=1 values=[None] verify=0 reloads=0 events=[]"
    ),
    "save_page_scale|reload_failed": (
        "False | "
        "calls=1 requests=['page:20@7'] records=1 values=[True] verify=0 reloads=1 events=[]"
    ),
    "save_page_scale|other_database": (
        "True | "
        "calls=1 requests=['page:20@None'] records=1 values=[True] verify=0 reloads=1 events=['DatabaseRefreshedEvent']"
    ),
    "save_page_scale|equivalent_path": (
        "True | "
        "calls=1 requests=['page:20@7'] records=1 values=[True] verify=0 reloads=1 events=['DatabaseRefreshedEvent']"
    ),
    "save_page_name|failure": (
        "False | "
        "calls=1 requests=['page:20@7'] records=0 values=[False] verify=0 reloads=0 events=[]"
    ),
    "save_page_name|denied": (
        "False | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "save_page_name|locked": (
        "False | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "save_page_name|conflict": (
        "False | "
        "calls=0 requests=['page:20@7'] records=0 values=[None] verify=0 reloads=0 events=['SynchronizationConflictEvent']"
    ),
    "save_page_name|unknown": (
        "False | "
        "calls=1 requests=['page:20@7'] records=1 values=[None] verify=0 reloads=0 events=[]"
    ),
    "save_page_name|reload_failed": (
        "False | "
        "calls=1 requests=['page:20@7'] records=1 values=[True] verify=0 reloads=1 events=[]"
    ),
    "save_page_name|other_database": (
        "True | "
        "calls=1 requests=['page:20@None'] records=1 values=[True] verify=0 reloads=1 events=['DatabaseRefreshedEvent']"
    ),
    "save_page_name|equivalent_path": (
        "True | "
        "calls=1 requests=['page:20@7'] records=1 values=[True] verify=0 reloads=1 events=['DatabaseRefreshedEvent']"
    ),
    "save_page_scales|failure": (
        "False | "
        "calls=2 requests=['page:20@7,page:21@7'] records=0 values=[(False, False)] verify=0 reloads=0 events=[]"
    ),
    "save_page_scales|denied": (
        "False | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "save_page_scales|locked": (
        "False | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "save_page_scales|conflict": (
        "False | "
        "calls=0 requests=['page:20@7,page:21@7'] records=0 values=[None] verify=0 reloads=0 events=['SynchronizationConflictEvent']"
    ),
    "save_page_scales|unknown": (
        "False | "
        "calls=2 requests=['page:20@7,page:21@7'] records=2 values=[None] verify=0 reloads=0 events=[]"
    ),
    "save_page_scales|reload_failed": (
        "False | "
        "calls=2 requests=['page:20@7,page:21@7'] records=2 values=[(True, True)] verify=0 reloads=1 events=[]"
    ),
    "save_page_scales|other_database": (
        "True | "
        "calls=2 requests=['page:20@None,page:21@None'] records=2 values=[(True, True)] verify=0 reloads=1 events=['DatabaseRefreshedEvent']"
    ),
    "save_page_scales|equivalent_path": (
        "True | "
        "calls=2 requests=['page:20@7,page:21@7'] records=2 values=[(True, True)] verify=0 reloads=1 events=['DatabaseRefreshedEvent']"
    ),
    "save_page_show_mode|failure": (
        "False | "
        "calls=1 requests=['page:20@7'] records=0 values=[False] verify=0 reloads=0 events=[]"
    ),
    "save_page_show_mode|denied": (
        "False | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "save_page_show_mode|locked": (
        "False | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "save_page_show_mode|conflict": (
        "False | "
        "calls=0 requests=['page:20@7'] records=0 values=[None] verify=0 reloads=0 events=['SynchronizationConflictEvent']"
    ),
    "save_page_show_mode|unknown": (
        "False | "
        "calls=1 requests=['page:20@7'] records=1 values=[None] verify=0 reloads=0 events=[]"
    ),
    "save_page_show_mode|reload_failed": (
        "False | "
        "calls=1 requests=['page:20@7'] records=1 values=[True] verify=0 reloads=1 events=[]"
    ),
    "save_page_show_mode|other_database": (
        "True | "
        "calls=1 requests=['page:20@None'] records=1 values=[True] verify=0 reloads=1 events=['DatabaseRefreshedEvent']"
    ),
    "save_page_show_mode|equivalent_path": (
        "True | "
        "calls=1 requests=['page:20@7'] records=1 values=[True] verify=0 reloads=1 events=['DatabaseRefreshedEvent']"
    ),
    "save_page_show_mode without refresh|failure": (
        "False | "
        "calls=1 requests=['page:20@7'] records=0 values=[False] verify=0 reloads=0 events=[]"
    ),
    "save_page_show_mode without refresh|denied": (
        "False | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "save_page_show_mode without refresh|locked": (
        "False | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "save_page_show_mode without refresh|conflict": (
        "False | "
        "calls=0 requests=['page:20@7'] records=0 values=[None] verify=0 reloads=0 events=['SynchronizationConflictEvent']"
    ),
    "save_page_show_mode without refresh|unknown": (
        "False | "
        "calls=1 requests=['page:20@7'] records=1 values=[None] verify=0 reloads=0 events=[]"
    ),
    "save_page_show_mode without refresh|reload_failed": (
        "True | "
        "calls=1 requests=['page:20@7'] records=1 values=[True] verify=0 reloads=0 events=[]"
    ),
    "save_page_show_mode without refresh|other_database": (
        "True | "
        "calls=1 requests=['page:20@None'] records=1 values=[True] verify=0 reloads=0 events=[]"
    ),
    "save_page_show_mode without refresh|equivalent_path": (
        "True | "
        "calls=1 requests=['page:20@7'] records=1 values=[True] verify=0 reloads=0 events=[]"
    ),
    "save_page_overlay_image|failure": (
        "False | "
        "calls=1 requests=['page:20@7'] records=0 values=[False] verify=0 reloads=0 events=[]"
    ),
    "save_page_overlay_image|denied": (
        "False | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "save_page_overlay_image|locked": (
        "False | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "save_page_overlay_image|conflict": (
        "False | "
        "calls=0 requests=['page:20@7'] records=0 values=[None] verify=0 reloads=0 events=['SynchronizationConflictEvent']"
    ),
    "save_page_overlay_image|unknown": (
        "False | "
        "calls=1 requests=['page:20@7'] records=1 values=[None] verify=0 reloads=0 events=[]"
    ),
    "save_page_overlay_image|reload_failed": (
        "False | "
        "calls=1 requests=['page:20@7'] records=1 values=[True] verify=0 reloads=1 events=[]"
    ),
    "save_page_overlay_image|other_database": (
        "True | "
        "calls=1 requests=['page:20@None'] records=1 values=[True] verify=0 reloads=1 events=['DatabaseRefreshedEvent']"
    ),
    "save_page_overlay_image|equivalent_path": (
        "True | "
        "calls=1 requests=['page:20@7'] records=1 values=[True] verify=0 reloads=1 events=['DatabaseRefreshedEvent']"
    ),
    "save_page_overlay_rect_result|failure": (
        "WriteReloadResult(value=None, write_success=False, reload_success=False, failure_reason=None, blocked_uids=[]) | "
        "calls=1 requests=['page:20@7'] records=0 values=[False] verify=0 reloads=0 events=[]"
    ),
    "save_page_overlay_rect_result|denied": (
        "WriteReloadResult(value=None, write_success=False, reload_success=False, failure_reason=None, blocked_uids=[]) | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "save_page_overlay_rect_result|locked": (
        "WriteReloadResult(value=None, write_success=False, reload_success=False, failure_reason=None, blocked_uids=[]) | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "save_page_overlay_rect_result|conflict": (
        "WriteReloadResult(value=None, write_success=False, reload_success=False, failure_reason=None, blocked_uids=[]) | "
        "calls=0 requests=['page:20@7'] records=0 values=[None] verify=0 reloads=0 events=['SynchronizationConflictEvent']"
    ),
    "save_page_overlay_rect_result|unknown": (
        "WriteReloadResult(value=None, write_success=False, reload_success=False, failure_reason=None, blocked_uids=[]) | "
        "calls=1 requests=['page:20@7'] records=1 values=[None] verify=0 reloads=0 events=[]"
    ),
    "save_page_overlay_rect_result|reload_failed": (
        "WriteReloadResult(value=None, write_success=True, reload_success=False, failure_reason=None, blocked_uids=[]) | "
        "calls=1 requests=['page:20@7'] records=1 values=[True] verify=0 reloads=1 events=[]"
    ),
    "save_page_overlay_rect_result|other_database": (
        "WriteReloadResult(value=None, write_success=True, reload_success=True, failure_reason=None, blocked_uids=[]) | "
        "calls=1 requests=['page:20@None'] records=1 values=[True] verify=0 reloads=1 events=['DatabaseRefreshedEvent']"
    ),
    "save_page_overlay_rect_result|equivalent_path": (
        "WriteReloadResult(value=None, write_success=True, reload_success=True, failure_reason=None, blocked_uids=[]) | "
        "calls=1 requests=['page:20@7'] records=1 values=[True] verify=0 reloads=1 events=['DatabaseRefreshedEvent']"
    ),
    "save_page_overlay_rect_result without refresh|failure": (
        "WriteReloadResult(value=None, write_success=False, reload_success=False, failure_reason=None, blocked_uids=[]) | "
        "calls=1 requests=['page:20@7'] records=0 values=[False] verify=0 reloads=0 events=[]"
    ),
    "save_page_overlay_rect_result without refresh|denied": (
        "WriteReloadResult(value=None, write_success=False, reload_success=False, failure_reason=None, blocked_uids=[]) | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "save_page_overlay_rect_result without refresh|locked": (
        "WriteReloadResult(value=None, write_success=False, reload_success=False, failure_reason=None, blocked_uids=[]) | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "save_page_overlay_rect_result without refresh|conflict": (
        "WriteReloadResult(value=None, write_success=False, reload_success=False, failure_reason=None, blocked_uids=[]) | "
        "calls=0 requests=['page:20@7'] records=0 values=[None] verify=0 reloads=0 events=['SynchronizationConflictEvent']"
    ),
    "save_page_overlay_rect_result without refresh|unknown": (
        "WriteReloadResult(value=None, write_success=False, reload_success=False, failure_reason=None, blocked_uids=[]) | "
        "calls=1 requests=['page:20@7'] records=1 values=[None] verify=0 reloads=0 events=[]"
    ),
    "save_page_overlay_rect_result without refresh|reload_failed": (
        "WriteReloadResult(value=None, write_success=True, reload_success=True, failure_reason=None, blocked_uids=[]) | "
        "calls=1 requests=['page:20@7'] records=1 values=[True] verify=0 reloads=0 events=[]"
    ),
    "save_page_overlay_rect_result without refresh|other_database": (
        "WriteReloadResult(value=None, write_success=True, reload_success=True, failure_reason=None, blocked_uids=[]) | "
        "calls=1 requests=['page:20@None'] records=1 values=[True] verify=0 reloads=0 events=[]"
    ),
    "save_page_overlay_rect_result without refresh|equivalent_path": (
        "WriteReloadResult(value=None, write_success=True, reload_success=True, failure_reason=None, blocked_uids=[]) | "
        "calls=1 requests=['page:20@7'] records=1 values=[True] verify=0 reloads=0 events=[]"
    ),
    "save_page_invert|failure": (
        "False | "
        "calls=1 requests=['page:20@7'] records=0 values=[False] verify=0 reloads=0 events=[]"
    ),
    "save_page_invert|denied": (
        "False | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "save_page_invert|locked": (
        "False | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "save_page_invert|conflict": (
        "False | "
        "calls=0 requests=['page:20@7'] records=0 values=[None] verify=0 reloads=0 events=['SynchronizationConflictEvent']"
    ),
    "save_page_invert|unknown": (
        "False | "
        "calls=1 requests=['page:20@7'] records=1 values=[None] verify=0 reloads=0 events=[]"
    ),
    "save_page_invert|reload_failed": (
        "True | "
        "calls=1 requests=['page:20@7'] records=1 values=[True] verify=0 reloads=0 events=[]"
    ),
    "save_page_invert|other_database": (
        "True | "
        "calls=1 requests=['page:20@None'] records=1 values=[True] verify=0 reloads=0 events=[]"
    ),
    "save_page_invert|equivalent_path": (
        "True | "
        "calls=1 requests=['page:20@7'] records=1 values=[True] verify=0 reloads=0 events=[]"
    ),
    "save_page_bitonal|failure": (
        "False | "
        "calls=1 requests=['page:20@7'] records=0 values=[False] verify=0 reloads=0 events=[]"
    ),
    "save_page_bitonal|denied": (
        "False | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "save_page_bitonal|locked": (
        "False | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "save_page_bitonal|conflict": (
        "False | "
        "calls=0 requests=['page:20@7'] records=0 values=[None] verify=0 reloads=0 events=['SynchronizationConflictEvent']"
    ),
    "save_page_bitonal|unknown": (
        "False | "
        "calls=1 requests=['page:20@7'] records=1 values=[None] verify=0 reloads=0 events=[]"
    ),
    "save_page_bitonal|reload_failed": (
        "True | "
        "calls=1 requests=['page:20@7'] records=1 values=[True] verify=0 reloads=0 events=[]"
    ),
    "save_page_bitonal|other_database": (
        "True | "
        "calls=1 requests=['page:20@None'] records=1 values=[True] verify=0 reloads=0 events=[]"
    ),
    "save_page_bitonal|equivalent_path": (
        "True | "
        "calls=1 requests=['page:20@7'] records=1 values=[True] verify=0 reloads=0 events=[]"
    ),
    "save_page_image_adjustments|failure": (
        "False | "
        "calls=1 requests=['page:20@7,page:21@7'] records=0 values=[False] verify=0 reloads=0 events=[]"
    ),
    "save_page_image_adjustments|denied": (
        "False | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "save_page_image_adjustments|locked": (
        "False | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "save_page_image_adjustments|conflict": (
        "False | "
        "calls=0 requests=['page:20@7,page:21@7'] records=0 values=[None] verify=0 reloads=0 events=['SynchronizationConflictEvent']"
    ),
    "save_page_image_adjustments|unknown": (
        "False | "
        "calls=1 requests=['page:20@7,page:21@7'] records=2 values=[None] verify=0 reloads=0 events=[]"
    ),
    "save_page_image_adjustments|reload_failed": (
        "False | "
        "calls=1 requests=['page:20@7,page:21@7'] records=2 values=[True] verify=0 reloads=1 events=[]"
    ),
    "save_page_image_adjustments|other_database": (
        "True | "
        "calls=1 requests=['page:20@None,page:21@None'] records=2 values=[True] verify=0 reloads=1 events=['DatabaseRefreshedEvent']"
    ),
    "save_page_image_adjustments|equivalent_path": (
        "True | "
        "calls=1 requests=['page:20@7,page:21@7'] records=2 values=[True] verify=0 reloads=1 events=['DatabaseRefreshedEvent']"
    ),
    "save_page_area|failure": (
        "False | "
        "calls=1 requests=['page:20@7'] records=0 values=[False] verify=0 reloads=0 events=[]"
    ),
    "save_page_area|denied": (
        "False | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "save_page_area|locked": (
        "False | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "save_page_area|conflict": (
        "False | "
        "calls=0 requests=['page:20@7'] records=0 values=[None] verify=0 reloads=0 events=['SynchronizationConflictEvent']"
    ),
    "save_page_area|unknown": (
        "False | "
        "calls=1 requests=['page:20@7'] records=1 values=[None] verify=0 reloads=0 events=[]"
    ),
    "save_page_area|reload_failed": (
        "False | "
        "calls=1 requests=['page:20@7'] records=1 values=[True] verify=0 reloads=1 events=[]"
    ),
    "save_page_area|other_database": (
        "True | "
        "calls=1 requests=['page:20@None'] records=1 values=[True] verify=0 reloads=1 events=['DatabaseRefreshedEvent']"
    ),
    "save_page_area|equivalent_path": (
        "True | "
        "calls=1 requests=['page:20@7'] records=1 values=[True] verify=0 reloads=1 events=['DatabaseRefreshedEvent']"
    ),
    "update_layer_show|failure": (
        "False | "
        "calls=1 requests=['layer:40@7'] records=0 values=[False] verify=0 reloads=0 events=[]"
    ),
    "update_layer_show|denied": (
        "False | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "update_layer_show|locked": (
        "False | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "update_layer_show|conflict": (
        "False | "
        "calls=0 requests=['layer:40@7'] records=0 values=[None] verify=0 reloads=0 events=['SynchronizationConflictEvent']"
    ),
    "update_layer_show|unknown": (
        "False | "
        "calls=1 requests=['layer:40@7'] records=1 values=[None] verify=0 reloads=0 events=[]"
    ),
    "update_layer_show|reload_failed": (
        "False | "
        "calls=1 requests=['layer:40@7'] records=1 values=[True] verify=0 reloads=1 events=[]"
    ),
    "update_layer_show|other_database": (
        "True | "
        "calls=1 requests=['layer:40@None'] records=1 values=[True] verify=0 reloads=1 events=['DatabaseRefreshedEvent']"
    ),
    "update_layer_show|equivalent_path": (
        "True | "
        "calls=1 requests=['layer:40@7'] records=1 values=[True] verify=0 reloads=1 events=['DatabaseRefreshedEvent']"
    ),
    "insert_layer_result|failure": (
        "WriteReloadResult(value=None, write_success=False, reload_success=False, failure_reason=None, blocked_uids=[]) | "
        "calls=1 requests=['layers_collection:7@7'] records=0 values=[None] verify=0 reloads=0 events=[]"
    ),
    "insert_layer_result|denied": (
        "WriteReloadResult(value=None, write_success=False, reload_success=False, failure_reason=None, blocked_uids=[]) | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "insert_layer_result|locked": (
        "WriteReloadResult(value=None, write_success=False, reload_success=False, failure_reason=None, blocked_uids=[]) | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "insert_layer_result|conflict": (
        "WriteReloadResult(value=None, write_success=False, reload_success=False, failure_reason=None, blocked_uids=[]) | "
        "calls=0 requests=['layers_collection:7@7'] records=0 values=[None] verify=0 reloads=0 events=['SynchronizationConflictEvent']"
    ),
    "insert_layer_result|unknown": (
        "WriteReloadResult(value=None, write_success=False, reload_success=False, failure_reason=None, blocked_uids=[]) | "
        "calls=1 requests=['layers_collection:7@7'] records=2 values=[None] verify=0 reloads=0 events=[]"
    ),
    "insert_layer_result|reload_failed": (
        "WriteReloadResult(value='41', write_success=True, reload_success=False, failure_reason=None, blocked_uids=[]) | "
        "calls=1 requests=['layers_collection:7@7'] records=2 values=['41'] verify=0 reloads=1 events=[]"
    ),
    "insert_layer_result|other_database": (
        "WriteReloadResult(value='41', write_success=True, reload_success=True, failure_reason=None, blocked_uids=[]) | "
        "calls=1 requests=['layers_collection:7@7'] records=2 values=['41'] verify=0 reloads=1 events=['DatabaseRefreshedEvent']"
    ),
    "insert_layer_result|equivalent_path": (
        "WriteReloadResult(value='41', write_success=True, reload_success=True, failure_reason=None, blocked_uids=[]) | "
        "calls=1 requests=['layers_collection:7@7'] records=2 values=['41'] verify=0 reloads=1 events=['DatabaseRefreshedEvent']"
    ),
    "insert_default_layer_result|failure": (
        "WriteReloadResult(value=None, write_success=False, reload_success=False, failure_reason=None, blocked_uids=[]) | "
        "calls=1 requests=['default_layers_collection:database@None'] records=0 values=[None] verify=0 reloads=0 events=[]"
    ),
    "insert_default_layer_result|denied": (
        "WriteReloadResult(value=None, write_success=False, reload_success=False, failure_reason=None, blocked_uids=[]) | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "insert_default_layer_result|locked": (
        "WriteReloadResult(value='42', write_success=True, reload_success=True, failure_reason=None, blocked_uids=[]) | "
        "calls=1 requests=['default_layers_collection:database@None'] records=1 values=['42'] verify=0 reloads=1 events=['DatabaseRefreshedEvent']"
    ),
    "insert_default_layer_result|conflict": (
        "WriteReloadResult(value=None, write_success=False, reload_success=False, failure_reason=None, blocked_uids=[]) | "
        "calls=0 requests=['default_layers_collection:database@None'] records=0 values=[None] verify=0 reloads=0 events=['SynchronizationConflictEvent']"
    ),
    "insert_default_layer_result|unknown": (
        "WriteReloadResult(value=None, write_success=False, reload_success=False, failure_reason=None, blocked_uids=[]) | "
        "calls=1 requests=['default_layers_collection:database@None'] records=1 values=[None] verify=0 reloads=0 events=[]"
    ),
    "insert_default_layer_result|reload_failed": (
        "WriteReloadResult(value='42', write_success=True, reload_success=False, failure_reason=None, blocked_uids=[]) | "
        "calls=1 requests=['default_layers_collection:database@None'] records=1 values=['42'] verify=0 reloads=1 events=[]"
    ),
    "insert_default_layer_result|other_database": (
        "WriteReloadResult(value='42', write_success=True, reload_success=True, failure_reason=None, blocked_uids=[]) | "
        "calls=1 requests=['default_layers_collection:database@None'] records=1 values=['42'] verify=0 reloads=1 events=['DatabaseRefreshedEvent']"
    ),
    "insert_default_layer_result|equivalent_path": (
        "WriteReloadResult(value='42', write_success=True, reload_success=True, failure_reason=None, blocked_uids=[]) | "
        "calls=1 requests=['default_layers_collection:database@None'] records=1 values=['42'] verify=0 reloads=1 events=['DatabaseRefreshedEvent']"
    ),
    "delete_layer|failure": (
        "False | "
        "calls=1 requests=['layer:40@7'] records=0 values=[False] verify=0 reloads=0 events=[]"
    ),
    "delete_layer|denied": (
        "False | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "delete_layer|locked": (
        "False | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "delete_layer|conflict": (
        "False | "
        "calls=0 requests=['layer:40@7'] records=0 values=[None] verify=0 reloads=0 events=['SynchronizationConflictEvent']"
    ),
    "delete_layer|unknown": (
        "False | "
        "calls=1 requests=['layer:40@7'] records=1 values=[None] verify=0 reloads=0 events=[]"
    ),
    "delete_layer|reload_failed": (
        "False | "
        "calls=1 requests=['layer:40@7'] records=1 values=[True] verify=0 reloads=1 events=[]"
    ),
    "delete_layer|other_database": (
        "True | "
        "calls=1 requests=['layer:40@None'] records=1 values=[True] verify=0 reloads=1 events=['DatabaseRefreshedEvent']"
    ),
    "delete_layer|equivalent_path": (
        "True | "
        "calls=1 requests=['layer:40@7'] records=1 values=[True] verify=0 reloads=1 events=['DatabaseRefreshedEvent']"
    ),
    "delete_layers|failure": (
        "BatchWriteResult(requested_uids=['40', '41'], succeeded_uids=[], failed_uids=['40'], reload_success=True) | "
        "calls=1 requests=['layer:40@7,layer:41@7'] records=0 values=[False] verify=0 reloads=0 events=[]"
    ),
    "delete_layers|denied": (
        "BatchWriteResult(requested_uids=['40', '41'], succeeded_uids=[], failed_uids=['40', '41'], reload_success=True) | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "delete_layers|locked": (
        "BatchWriteResult(requested_uids=['40', '41'], succeeded_uids=[], failed_uids=['40', '41'], reload_success=True) | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "delete_layers|conflict": (
        "BatchWriteResult(requested_uids=['40', '41'], succeeded_uids=[], failed_uids=['40', '41'], reload_success=True) | "
        "calls=0 requests=['layer:40@7,layer:41@7'] records=0 values=[None] verify=0 reloads=0 events=['SynchronizationConflictEvent']"
    ),
    "delete_layers|unknown": (
        "BatchWriteResult(requested_uids=['40', '41'], succeeded_uids=[], failed_uids=['40', '41'], reload_success=True) | "
        "calls=2 requests=['layer:40@7,layer:41@7'] records=2 values=[None] verify=0 reloads=0 events=[]"
    ),
    "delete_layers|reload_failed": (
        "BatchWriteResult(requested_uids=['40', '41'], succeeded_uids=['40', '41'], failed_uids=[], reload_success=False) | "
        "calls=2 requests=['layer:40@7,layer:41@7'] records=2 values=[True] verify=0 reloads=1 events=[]"
    ),
    "delete_layers|other_database": (
        "BatchWriteResult(requested_uids=['40', '41'], succeeded_uids=['40', '41'], failed_uids=[], reload_success=True) | "
        "calls=2 requests=['layer:40@None,layer:41@None'] records=2 values=[True] verify=0 reloads=1 events=['DatabaseRefreshedEvent']"
    ),
    "delete_layers|equivalent_path": (
        "BatchWriteResult(requested_uids=['40', '41'], succeeded_uids=['40', '41'], failed_uids=[], reload_success=True) | "
        "calls=2 requests=['layer:40@7,layer:41@7'] records=2 values=[True] verify=0 reloads=1 events=['DatabaseRefreshedEvent']"
    ),
    "delete_default_layers|failure": (
        "BatchWriteResult(requested_uids=['40', '41'], succeeded_uids=[], failed_uids=['40'], reload_success=True) | "
        "calls=1 requests=['default_layers_collection:database@None'] records=0 values=[False] verify=0 reloads=0 events=[]"
    ),
    "delete_default_layers|denied": (
        "BatchWriteResult(requested_uids=['40', '41'], succeeded_uids=[], failed_uids=['40', '41'], reload_success=True) | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "delete_default_layers|locked": (
        "BatchWriteResult(requested_uids=['40', '41'], succeeded_uids=['40', '41'], failed_uids=[], reload_success=True) | "
        "calls=2 requests=['default_layers_collection:database@None'] records=1 values=[True] verify=0 reloads=1 events=['DatabaseRefreshedEvent']"
    ),
    "delete_default_layers|conflict": (
        "BatchWriteResult(requested_uids=['40', '41'], succeeded_uids=[], failed_uids=['40', '41'], reload_success=True) | "
        "calls=0 requests=['default_layers_collection:database@None'] records=0 values=[None] verify=0 reloads=0 events=['SynchronizationConflictEvent']"
    ),
    "delete_default_layers|unknown": (
        "BatchWriteResult(requested_uids=['40', '41'], succeeded_uids=[], failed_uids=['40', '41'], reload_success=True) | "
        "calls=2 requests=['default_layers_collection:database@None'] records=1 values=[None] verify=0 reloads=0 events=[]"
    ),
    "delete_default_layers|reload_failed": (
        "BatchWriteResult(requested_uids=['40', '41'], succeeded_uids=['40', '41'], failed_uids=[], reload_success=False) | "
        "calls=2 requests=['default_layers_collection:database@None'] records=1 values=[True] verify=0 reloads=1 events=[]"
    ),
    "delete_default_layers|other_database": (
        "BatchWriteResult(requested_uids=['40', '41'], succeeded_uids=['40', '41'], failed_uids=[], reload_success=True) | "
        "calls=2 requests=['default_layers_collection:database@None'] records=1 values=[True] verify=0 reloads=1 events=['DatabaseRefreshedEvent']"
    ),
    "delete_default_layers|equivalent_path": (
        "BatchWriteResult(requested_uids=['40', '41'], succeeded_uids=['40', '41'], failed_uids=[], reload_success=True) | "
        "calls=2 requests=['default_layers_collection:database@None'] records=1 values=[True] verify=0 reloads=1 events=['DatabaseRefreshedEvent']"
    ),
    "update_all_layers_show|failure": (
        "False | "
        "calls=1 requests=['layers_collection:7@7'] records=0 values=[False] verify=0 reloads=0 events=[]"
    ),
    "update_all_layers_show|denied": (
        "False | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "update_all_layers_show|locked": (
        "False | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "update_all_layers_show|conflict": (
        "False | "
        "calls=0 requests=['layers_collection:7@7'] records=0 values=[None] verify=0 reloads=0 events=['SynchronizationConflictEvent']"
    ),
    "update_all_layers_show|unknown": (
        "False | "
        "calls=1 requests=['layers_collection:7@7'] records=1 values=[None] verify=0 reloads=0 events=[]"
    ),
    "update_all_layers_show|reload_failed": (
        "False | "
        "calls=1 requests=['layers_collection:7@7'] records=1 values=[True] verify=0 reloads=1 events=[]"
    ),
    "update_all_layers_show|other_database": (
        "True | "
        "calls=1 requests=['layers_collection:7@7'] records=1 values=[True] verify=0 reloads=1 events=['DatabaseRefreshedEvent']"
    ),
    "update_all_layers_show|equivalent_path": (
        "True | "
        "calls=1 requests=['layers_collection:7@7'] records=1 values=[True] verify=0 reloads=1 events=['DatabaseRefreshedEvent']"
    ),
    "update_all_default_layers_show|failure": (
        "False | "
        "calls=1 requests=['default_layers_collection:database@None'] records=0 values=[False] verify=0 reloads=0 events=[]"
    ),
    "update_all_default_layers_show|denied": (
        "False | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "update_all_default_layers_show|locked": (
        "True | "
        "calls=1 requests=['default_layers_collection:database@None'] records=1 values=[True] verify=0 reloads=1 events=['DatabaseRefreshedEvent']"
    ),
    "update_all_default_layers_show|conflict": (
        "False | "
        "calls=0 requests=['default_layers_collection:database@None'] records=0 values=[None] verify=0 reloads=0 events=['SynchronizationConflictEvent']"
    ),
    "update_all_default_layers_show|unknown": (
        "False | "
        "calls=1 requests=['default_layers_collection:database@None'] records=1 values=[None] verify=0 reloads=0 events=[]"
    ),
    "update_all_default_layers_show|reload_failed": (
        "False | "
        "calls=1 requests=['default_layers_collection:database@None'] records=1 values=[True] verify=0 reloads=1 events=[]"
    ),
    "update_all_default_layers_show|other_database": (
        "True | "
        "calls=1 requests=['default_layers_collection:database@None'] records=1 values=[True] verify=0 reloads=1 events=['DatabaseRefreshedEvent']"
    ),
    "update_all_default_layers_show|equivalent_path": (
        "True | "
        "calls=1 requests=['default_layers_collection:database@None'] records=1 values=[True] verify=0 reloads=1 events=['DatabaseRefreshedEvent']"
    ),
    "swap_layer_sequence|failure": (
        "False | "
        "calls=1 requests=['layers_collection:7@7'] records=0 values=[False] verify=0 reloads=0 events=[]"
    ),
    "swap_layer_sequence|denied": (
        "False | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "swap_layer_sequence|locked": (
        "False | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "swap_layer_sequence|conflict": (
        "False | "
        "calls=0 requests=['layers_collection:7@7'] records=0 values=[None] verify=0 reloads=0 events=['SynchronizationConflictEvent']"
    ),
    "swap_layer_sequence|unknown": (
        "False | "
        "calls=1 requests=['layers_collection:7@7'] records=1 values=[None] verify=0 reloads=0 events=[]"
    ),
    "swap_layer_sequence|reload_failed": (
        "False | "
        "calls=1 requests=['layers_collection:7@7'] records=1 values=[True] verify=0 reloads=1 events=[]"
    ),
    "swap_layer_sequence|other_database": (
        "True | "
        "calls=1 requests=['layers_collection:database@None'] records=1 values=[True] verify=0 reloads=1 events=['DatabaseRefreshedEvent']"
    ),
    "swap_layer_sequence|equivalent_path": (
        "True | "
        "calls=1 requests=['layers_collection:7@7'] records=1 values=[True] verify=0 reloads=1 events=['DatabaseRefreshedEvent']"
    ),
    "swap_default_layer_sequence|failure": (
        "False | "
        "calls=1 requests=['default_layers_collection:database@None'] records=0 values=[False] verify=0 reloads=0 events=[]"
    ),
    "swap_default_layer_sequence|denied": (
        "False | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "swap_default_layer_sequence|locked": (
        "True | "
        "calls=1 requests=['default_layers_collection:database@None'] records=1 values=[True] verify=0 reloads=1 events=['DatabaseRefreshedEvent']"
    ),
    "swap_default_layer_sequence|conflict": (
        "False | "
        "calls=0 requests=['default_layers_collection:database@None'] records=0 values=[None] verify=0 reloads=0 events=['SynchronizationConflictEvent']"
    ),
    "swap_default_layer_sequence|unknown": (
        "False | "
        "calls=1 requests=['default_layers_collection:database@None'] records=1 values=[None] verify=0 reloads=0 events=[]"
    ),
    "swap_default_layer_sequence|reload_failed": (
        "False | "
        "calls=1 requests=['default_layers_collection:database@None'] records=1 values=[True] verify=0 reloads=1 events=[]"
    ),
    "swap_default_layer_sequence|other_database": (
        "True | "
        "calls=1 requests=['default_layers_collection:database@None'] records=1 values=[True] verify=0 reloads=1 events=['DatabaseRefreshedEvent']"
    ),
    "swap_default_layer_sequence|equivalent_path": (
        "True | "
        "calls=1 requests=['default_layers_collection:database@None'] records=1 values=[True] verify=0 reloads=1 events=['DatabaseRefreshedEvent']"
    ),
    "update_layer_name|failure": (
        "False | "
        "calls=1 requests=['layer:40@7'] records=0 values=[False] verify=0 reloads=0 events=[]"
    ),
    "update_layer_name|denied": (
        "False | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "update_layer_name|locked": (
        "False | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "update_layer_name|conflict": (
        "False | "
        "calls=0 requests=['layer:40@7'] records=0 values=[None] verify=0 reloads=0 events=['SynchronizationConflictEvent']"
    ),
    "update_layer_name|unknown": (
        "False | "
        "calls=1 requests=['layer:40@7'] records=1 values=[None] verify=0 reloads=0 events=[]"
    ),
    "update_layer_name|reload_failed": (
        "False | "
        "calls=1 requests=['layer:40@7'] records=1 values=[True] verify=0 reloads=1 events=[]"
    ),
    "update_layer_name|other_database": (
        "True | "
        "calls=1 requests=['layer:40@None'] records=1 values=[True] verify=0 reloads=1 events=['DatabaseRefreshedEvent']"
    ),
    "update_layer_name|equivalent_path": (
        "True | "
        "calls=1 requests=['layer:40@7'] records=1 values=[True] verify=0 reloads=1 events=['DatabaseRefreshedEvent']"
    ),
    "update_default_layer_name|failure": (
        "False | "
        "calls=1 requests=['default_layers_collection:database@None'] records=0 values=[False] verify=0 reloads=0 events=[]"
    ),
    "update_default_layer_name|denied": (
        "False | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "update_default_layer_name|locked": (
        "True | "
        "calls=1 requests=['default_layers_collection:database@None'] records=1 values=[True] verify=0 reloads=1 events=['DatabaseRefreshedEvent']"
    ),
    "update_default_layer_name|conflict": (
        "False | "
        "calls=0 requests=['default_layers_collection:database@None'] records=0 values=[None] verify=0 reloads=0 events=['SynchronizationConflictEvent']"
    ),
    "update_default_layer_name|unknown": (
        "False | "
        "calls=1 requests=['default_layers_collection:database@None'] records=1 values=[None] verify=0 reloads=0 events=[]"
    ),
    "update_default_layer_name|reload_failed": (
        "False | "
        "calls=1 requests=['default_layers_collection:database@None'] records=1 values=[True] verify=0 reloads=1 events=[]"
    ),
    "update_default_layer_name|other_database": (
        "True | "
        "calls=1 requests=['default_layers_collection:database@None'] records=1 values=[True] verify=0 reloads=1 events=['DatabaseRefreshedEvent']"
    ),
    "update_default_layer_name|equivalent_path": (
        "True | "
        "calls=1 requests=['default_layers_collection:database@None'] records=1 values=[True] verify=0 reloads=1 events=['DatabaseRefreshedEvent']"
    ),
    "update_default_layer_show|failure": (
        "False | "
        "calls=1 requests=['default_layers_collection:database@None'] records=0 values=[False] verify=0 reloads=0 events=[]"
    ),
    "update_default_layer_show|denied": (
        "False | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "update_default_layer_show|locked": (
        "True | "
        "calls=1 requests=['default_layers_collection:database@None'] records=1 values=[True] verify=0 reloads=1 events=['DatabaseRefreshedEvent']"
    ),
    "update_default_layer_show|conflict": (
        "False | "
        "calls=0 requests=['default_layers_collection:database@None'] records=0 values=[None] verify=0 reloads=0 events=['SynchronizationConflictEvent']"
    ),
    "update_default_layer_show|unknown": (
        "False | "
        "calls=1 requests=['default_layers_collection:database@None'] records=1 values=[None] verify=0 reloads=0 events=[]"
    ),
    "update_default_layer_show|reload_failed": (
        "False | "
        "calls=1 requests=['default_layers_collection:database@None'] records=1 values=[True] verify=0 reloads=1 events=[]"
    ),
    "update_default_layer_show|other_database": (
        "True | "
        "calls=1 requests=['default_layers_collection:database@None'] records=1 values=[True] verify=0 reloads=1 events=['DatabaseRefreshedEvent']"
    ),
    "update_default_layer_show|equivalent_path": (
        "True | "
        "calls=1 requests=['default_layers_collection:database@None'] records=1 values=[True] verify=0 reloads=1 events=['DatabaseRefreshedEvent']"
    ),
    "save_page_view_state|failure": (
        "False | "
        "calls=1 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "save_page_view_state|denied": (
        "True | " "calls=1 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "save_page_view_state|locked": (
        "False | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "save_page_view_state|conflict": (
        "True | " "calls=1 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "save_page_view_state|unknown": (
        "True | " "calls=1 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "save_page_view_state|reload_failed": (
        "True | " "calls=1 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "save_page_view_state|other_database": (
        "True | " "calls=1 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "save_page_view_state|equivalent_path": (
        "True | " "calls=1 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "save_bid_selected_page|failure": (
        "False | "
        "calls=1 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "save_bid_selected_page|denied": (
        "True | " "calls=1 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "save_bid_selected_page|locked": (
        "False | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "save_bid_selected_page|conflict": (
        "True | " "calls=1 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "save_bid_selected_page|unknown": (
        "True | " "calls=1 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "save_bid_selected_page|reload_failed": (
        "True | " "calls=1 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "save_bid_selected_page|other_database": (
        "True | " "calls=1 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "save_bid_selected_page|equivalent_path": (
        "True | " "calls=1 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "save_cover_sheet|failure": (
        "False | "
        "calls=1 requests=['cover_sheet:7@7'] records=0 values=[False] verify=0 reloads=0 events=[]"
    ),
    "save_cover_sheet|denied": (
        "False | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "save_cover_sheet|locked": (
        "False | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "save_cover_sheet|conflict": (
        "False | "
        "calls=0 requests=['cover_sheet:7@7'] records=0 values=[None] verify=0 reloads=0 events=['SynchronizationConflictEvent']"
    ),
    "save_cover_sheet|unknown": (
        "False | "
        "calls=1 requests=['cover_sheet:7@7'] records=1 values=[None] verify=0 reloads=0 events=[]"
    ),
    "save_cover_sheet|reload_failed": (
        "False | "
        "calls=1 requests=['cover_sheet:7@7'] records=1 values=[True] verify=0 reloads=1 events=[]"
    ),
    "save_cover_sheet|other_database": (
        "True | "
        "calls=1 requests=['cover_sheet:7@7'] records=1 values=[True] verify=0 reloads=1 events=['DatabaseRefreshedEvent']"
    ),
    "save_cover_sheet|equivalent_path": (
        "True | "
        "calls=1 requests=['cover_sheet:7@7'] records=1 values=[True] verify=0 reloads=1 events=['DatabaseRefreshedEvent']"
    ),
    "delete_pages|failure": (
        "False | "
        "calls=1 requests=['page:20@7,page:21@7'] records=0 values=[False] verify=0 reloads=0 events=[]"
    ),
    "delete_pages|denied": (
        "False | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "delete_pages|locked": (
        "False | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "delete_pages|conflict": (
        "False | "
        "calls=0 requests=['page:20@7,page:21@7'] records=0 values=[None] verify=0 reloads=0 events=['SynchronizationConflictEvent']"
    ),
    "delete_pages|unknown": (
        "False | "
        "calls=1 requests=['page:20@7,page:21@7'] records=2 values=[None] verify=0 reloads=0 events=[]"
    ),
    "delete_pages|reload_failed": (
        "False | "
        "calls=1 requests=['page:20@7,page:21@7'] records=2 values=[True] verify=0 reloads=1 events=[]"
    ),
    "delete_pages|other_database": (
        "True | "
        "calls=1 requests=['page:20@None,page:21@None'] records=2 values=[True] verify=0 reloads=1 events=['DatabaseRefreshedEvent']"
    ),
    "delete_pages|equivalent_path": (
        "True | "
        "calls=1 requests=['page:20@7,page:21@7'] records=2 values=[True] verify=0 reloads=1 events=['DatabaseRefreshedEvent']"
    ),
    "update_bid_job_status|failure": (
        "False | "
        "calls=1 requests=['bid:7@7'] records=0 values=[False] verify=0 reloads=0 events=[]"
    ),
    "update_bid_job_status|denied": (
        "False | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "update_bid_job_status|locked": (
        "True | "
        "calls=1 requests=['bid:7@7'] records=1 values=[True] verify=0 reloads=1 events=['DatabaseRefreshedEvent']"
    ),
    "update_bid_job_status|conflict": (
        "False | "
        "calls=0 requests=['bid:7@7'] records=0 values=[None] verify=0 reloads=0 events=['SynchronizationConflictEvent']"
    ),
    "update_bid_job_status|unknown": (
        "False | "
        "calls=1 requests=['bid:7@7'] records=1 values=[None] verify=0 reloads=0 events=[]"
    ),
    "update_bid_job_status|reload_failed": (
        "False | "
        "calls=1 requests=['bid:7@7'] records=1 values=[True] verify=0 reloads=1 events=[]"
    ),
    "update_bid_job_status|other_database": (
        "True | "
        "calls=1 requests=['bid:7@7'] records=1 values=[True] verify=0 reloads=1 events=['DatabaseRefreshedEvent']"
    ),
    "update_bid_job_status|equivalent_path": (
        "True | "
        "calls=1 requests=['bid:7@7'] records=1 values=[True] verify=0 reloads=1 events=['DatabaseRefreshedEvent']"
    ),
    "save_job_statuses|failure": (
        "None | "
        "calls=1 requests=['job_statuses_collection:database@None'] records=0 values=[None] verify=0 reloads=0 events=[]"
    ),
    "save_job_statuses|denied": (
        "None | " "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "save_job_statuses|locked": (
        "{'n': '5'} | "
        "calls=1 requests=['job_statuses_collection:database@None'] records=1 values=[{'n': '5'}] verify=0 reloads=1 events=['DatabaseRefreshedEvent']"
    ),
    "save_job_statuses|conflict": (
        "None | "
        "calls=0 requests=['job_statuses_collection:database@None'] records=0 values=[None] verify=0 reloads=0 events=['SynchronizationConflictEvent']"
    ),
    "save_job_statuses|unknown": (
        "None | "
        "calls=1 requests=['job_statuses_collection:database@None'] records=1 values=[None] verify=0 reloads=0 events=[]"
    ),
    "save_job_statuses|reload_failed": (
        "None | "
        "calls=1 requests=['job_statuses_collection:database@None'] records=1 values=[{'n': '5'}] verify=0 reloads=1 events=[]"
    ),
    "save_job_statuses|other_database": (
        "{'n': '5'} | "
        "calls=1 requests=['job_statuses_collection:database@None'] records=1 values=[{'n': '5'}] verify=0 reloads=1 events=['DatabaseRefreshedEvent']"
    ),
    "save_job_statuses|equivalent_path": (
        "{'n': '5'} | "
        "calls=1 requests=['job_statuses_collection:database@None'] records=1 values=[{'n': '5'}] verify=0 reloads=1 events=['DatabaseRefreshedEvent']"
    ),
    "save_employees_result|failure": (
        "WriteReloadResult(value=None, write_success=False, reload_success=False, failure_reason=None, blocked_uids=[]) | "
        "calls=1 requests=['employees_collection:database@None'] records=0 values=[None] verify=0 reloads=0 events=[]"
    ),
    "save_employees_result|denied": (
        "WriteReloadResult(value=None, write_success=False, reload_success=False, failure_reason=None, blocked_uids=[]) | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "save_employees_result|locked": (
        "WriteReloadResult(value={'n': '6'}, write_success=True, reload_success=True, failure_reason=None, blocked_uids=[]) | "
        "calls=1 requests=['employees_collection:database@None'] records=1 values=[{'n': '6'}] verify=0 reloads=1 events=['DatabaseRefreshedEvent']"
    ),
    "save_employees_result|conflict": (
        "WriteReloadResult(value=None, write_success=False, reload_success=False, failure_reason=None, blocked_uids=[]) | "
        "calls=0 requests=['employees_collection:database@None'] records=0 values=[None] verify=0 reloads=0 events=['SynchronizationConflictEvent']"
    ),
    "save_employees_result|unknown": (
        "WriteReloadResult(value=None, write_success=False, reload_success=False, failure_reason=None, blocked_uids=[]) | "
        "calls=1 requests=['employees_collection:database@None'] records=1 values=[None] verify=0 reloads=0 events=[]"
    ),
    "save_employees_result|reload_failed": (
        "WriteReloadResult(value={'n': '6'}, write_success=True, reload_success=False, failure_reason=None, blocked_uids=[]) | "
        "calls=1 requests=['employees_collection:database@None'] records=1 values=[{'n': '6'}] verify=0 reloads=1 events=[]"
    ),
    "save_employees_result|other_database": (
        "WriteReloadResult(value={'n': '6'}, write_success=True, reload_success=True, failure_reason=None, blocked_uids=[]) | "
        "calls=1 requests=['employees_collection:database@None'] records=1 values=[{'n': '6'}] verify=0 reloads=1 events=['DatabaseRefreshedEvent']"
    ),
    "save_employees_result|equivalent_path": (
        "WriteReloadResult(value={'n': '6'}, write_success=True, reload_success=True, failure_reason=None, blocked_uids=[]) | "
        "calls=1 requests=['employees_collection:database@None'] records=1 values=[{'n': '6'}] verify=0 reloads=1 events=['DatabaseRefreshedEvent']"
    ),
    "save_pay_classes|failure": (
        "None | "
        "calls=1 requests=['pay_classes_collection:database@None'] records=0 values=[None] verify=0 reloads=0 events=[]"
    ),
    "save_pay_classes|denied": (
        "None | " "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "save_pay_classes|locked": (
        "{'n': '7'} | "
        "calls=1 requests=['pay_classes_collection:database@None'] records=1 values=[{'n': '7'}] verify=0 reloads=1 events=['DatabaseRefreshedEvent']"
    ),
    "save_pay_classes|conflict": (
        "None | "
        "calls=0 requests=['pay_classes_collection:database@None'] records=0 values=[None] verify=0 reloads=0 events=['SynchronizationConflictEvent']"
    ),
    "save_pay_classes|unknown": (
        "None | "
        "calls=1 requests=['pay_classes_collection:database@None'] records=1 values=[None] verify=0 reloads=0 events=[]"
    ),
    "save_pay_classes|reload_failed": (
        "None | "
        "calls=1 requests=['pay_classes_collection:database@None'] records=1 values=[{'n': '7'}] verify=0 reloads=1 events=[]"
    ),
    "save_pay_classes|other_database": (
        "{'n': '7'} | "
        "calls=1 requests=['pay_classes_collection:database@None'] records=1 values=[{'n': '7'}] verify=0 reloads=1 events=['DatabaseRefreshedEvent']"
    ),
    "save_pay_classes|equivalent_path": (
        "{'n': '7'} | "
        "calls=1 requests=['pay_classes_collection:database@None'] records=1 values=[{'n': '7'}] verify=0 reloads=1 events=['DatabaseRefreshedEvent']"
    ),
    "save_job_statuses unchanged|failure": ("no use case is reached"),
    "save_job_statuses unchanged|denied": (
        "{} | " "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "save_job_statuses unchanged|locked": (
        "{} | " "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "save_job_statuses unchanged|conflict": (
        "{} | " "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "save_job_statuses unchanged|unknown": (
        "{} | " "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "save_job_statuses unchanged|reload_failed": (
        "{} | " "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "save_job_statuses unchanged|other_database": (
        "{} | " "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "save_job_statuses unchanged|equivalent_path": (
        "{} | " "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "create_project|failure": (
        "None | "
        "calls=1 requests=['projects_collection:database@None'] records=0 values=[None] verify=0 reloads=0 events=[]"
    ),
    "create_project|denied": (
        "None | " "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "create_project|locked": (
        "'9' | "
        "calls=1 requests=['projects_collection:database@None'] records=2 values=['9'] verify=0 reloads=1 events=['DatabaseRefreshedEvent']"
    ),
    "create_project|conflict": (
        "None | "
        "calls=0 requests=['projects_collection:database@None'] records=0 values=[None] verify=0 reloads=0 events=['SynchronizationConflictEvent']"
    ),
    "create_project|unknown": (
        "None | "
        "calls=1 requests=['projects_collection:database@None'] records=2 values=[None] verify=0 reloads=0 events=[]"
    ),
    "create_project|reload_failed": (
        "None | "
        "calls=1 requests=['projects_collection:database@None'] records=2 values=['9'] verify=0 reloads=1 events=[]"
    ),
    "create_project|other_database": (
        "'9' | "
        "calls=1 requests=['projects_collection:database@None'] records=2 values=['9'] verify=0 reloads=1 events=['DatabaseRefreshedEvent']"
    ),
    "create_project|equivalent_path": (
        "'9' | "
        "calls=1 requests=['projects_collection:database@None'] records=2 values=['9'] verify=0 reloads=1 events=['DatabaseRefreshedEvent']"
    ),
    "create_bid|failure": (
        "None | "
        "calls=1 requests=['project_bids:3@None'] records=0 values=[None] verify=0 reloads=0 events=[]"
    ),
    "create_bid|denied": (
        "None | " "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "create_bid|locked": (
        "'13' | "
        "calls=1 requests=['project_bids:3@None'] records=2 values=['13'] verify=0 reloads=1 events=['DatabaseRefreshedEvent']"
    ),
    "create_bid|conflict": (
        "None | "
        "calls=0 requests=['project_bids:3@None'] records=0 values=[None] verify=0 reloads=0 events=['SynchronizationConflictEvent']"
    ),
    "create_bid|unknown": (
        "None | "
        "calls=1 requests=['project_bids:3@None'] records=2 values=[None] verify=0 reloads=0 events=[]"
    ),
    "create_bid|reload_failed": (
        "None | "
        "calls=1 requests=['project_bids:3@None'] records=2 values=['13'] verify=0 reloads=1 events=[]"
    ),
    "create_bid|other_database": (
        "'13' | "
        "calls=1 requests=['project_bids:3@None'] records=2 values=['13'] verify=0 reloads=1 events=['DatabaseRefreshedEvent']"
    ),
    "create_bid|equivalent_path": (
        "'13' | "
        "calls=1 requests=['project_bids:3@None'] records=2 values=['13'] verify=0 reloads=1 events=['DatabaseRefreshedEvent']"
    ),
    "duplicate_bid|failure": (
        "None | "
        "calls=1 requests=['bid:7@7'] records=0 values=[None] verify=0 reloads=0 events=[]"
    ),
    "duplicate_bid|denied": (
        "None | " "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "duplicate_bid|locked": (
        "'12' | "
        "calls=1 requests=['bid:7@7'] records=1 values=['12'] verify=0 reloads=1 events=['DatabaseRefreshedEvent']"
    ),
    "duplicate_bid|conflict": (
        "None | "
        "calls=0 requests=['bid:7@7'] records=0 values=[None] verify=0 reloads=0 events=['SynchronizationConflictEvent']"
    ),
    "duplicate_bid|unknown": (
        "None | "
        "calls=1 requests=['bid:7@7'] records=1 values=[None] verify=0 reloads=0 events=[]"
    ),
    "duplicate_bid|reload_failed": (
        "None | "
        "calls=1 requests=['bid:7@7'] records=1 values=['12'] verify=0 reloads=1 events=[]"
    ),
    "duplicate_bid|other_database": (
        "'12' | "
        "calls=1 requests=['bid:7@7'] records=1 values=['12'] verify=0 reloads=1 events=['DatabaseRefreshedEvent']"
    ),
    "duplicate_bid|equivalent_path": (
        "'12' | "
        "calls=1 requests=['bid:7@7'] records=1 values=['12'] verify=0 reloads=1 events=['DatabaseRefreshedEvent']"
    ),
    "insert_layer|failure": (
        "None | "
        "calls=1 requests=['layers_collection:7@7'] records=0 values=[None] verify=0 reloads=0 events=[]"
    ),
    "insert_layer|denied": (
        "None | " "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "insert_layer|locked": (
        "None | " "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "insert_layer|conflict": (
        "None | "
        "calls=0 requests=['layers_collection:7@7'] records=0 values=[None] verify=0 reloads=0 events=['SynchronizationConflictEvent']"
    ),
    "insert_layer|unknown": (
        "None | "
        "calls=1 requests=['layers_collection:7@7'] records=2 values=[None] verify=0 reloads=0 events=[]"
    ),
    "insert_layer|reload_failed": (
        "None | "
        "calls=1 requests=['layers_collection:7@7'] records=2 values=['41'] verify=0 reloads=1 events=[]"
    ),
    "insert_layer|other_database": (
        "'41' | "
        "calls=1 requests=['layers_collection:7@7'] records=2 values=['41'] verify=0 reloads=1 events=['DatabaseRefreshedEvent']"
    ),
    "insert_layer|equivalent_path": (
        "'41' | "
        "calls=1 requests=['layers_collection:7@7'] records=2 values=['41'] verify=0 reloads=1 events=['DatabaseRefreshedEvent']"
    ),
    "duplicate_conditions|failure": (
        "[] | "
        "calls=1 requests=['conditions_collection:7@7'] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "duplicate_conditions|denied": (
        "[] | " "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "duplicate_conditions|locked": (
        "[] | " "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "duplicate_conditions|conflict": (
        "[] | "
        "calls=0 requests=['conditions_collection:7@7'] records=0 values=[None] verify=0 reloads=0 events=['SynchronizationConflictEvent']"
    ),
    "duplicate_conditions|unknown": (
        "[] | "
        "calls=1 requests=['conditions_collection:7@7'] records=3 values=[None] verify=0 reloads=0 events=[]"
    ),
    "duplicate_conditions|reload_failed": (
        "[] | "
        "calls=1 requests=['conditions_collection:7@7'] records=3 values=[('c9', 'c10')] verify=0 reloads=1 events=[]"
    ),
    "duplicate_conditions|other_database": (
        "['c9', 'c10'] | "
        "calls=1 requests=['conditions_collection:7@7'] records=3 values=[('c9', 'c10')] verify=0 reloads=1 events=['ConditionsChangedEvent']"
    ),
    "duplicate_conditions|equivalent_path": (
        "['c9', 'c10'] | "
        "calls=1 requests=['conditions_collection:7@7'] records=3 values=[('c9', 'c10')] verify=0 reloads=1 events=['ConditionsChangedEvent']"
    ),
    "insert_takeoffs|failure": (
        "'raised RuntimeError: The takeoff insertion returned an incomplete authoritative identity set.' | "
        "calls=1 requests=['takeoffs_collection:7@7'] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "insert_takeoffs|denied": (
        "[] | " "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "insert_takeoffs|locked": (
        "[] | " "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "insert_takeoffs|conflict": (
        "[] | "
        "calls=0 requests=['takeoffs_collection:7@7'] records=0 values=[None] verify=0 reloads=0 events=['SynchronizationConflictEvent']"
    ),
    "insert_takeoffs|unknown": (
        "[] | "
        "calls=1 requests=['takeoffs_collection:7@7'] records=3 values=[None] verify=0 reloads=0 events=[]"
    ),
    "insert_takeoffs|reload_failed": (
        "[] | "
        "calls=1 requests=['takeoffs_collection:7@7'] records=3 values=[['101', '102']] verify=0 reloads=1 events=[]"
    ),
    "insert_takeoffs|other_database": (
        "['101', '102'] | "
        "calls=1 requests=['takeoffs_collection:7@7'] records=3 values=[['101', '102']] verify=0 reloads=1 events=['DatabaseRefreshedEvent']"
    ),
    "insert_takeoffs|equivalent_path": (
        "['101', '102'] | "
        "calls=1 requests=['takeoffs_collection:7@7'] records=3 values=[['101', '102']] verify=0 reloads=1 events=['DatabaseRefreshedEvent']"
    ),
    "insert_takeoffs_result without refresh|failure": (
        "'raised RuntimeError: The takeoff insertion returned an incomplete authoritative identity set.' | "
        "calls=1 requests=['takeoffs_collection:7@7'] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "insert_takeoffs_result without refresh|denied": (
        "WriteReloadResult(value=[], write_success=False, reload_success=False, failure_reason=None, blocked_uids=[]) | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "insert_takeoffs_result without refresh|locked": (
        "WriteReloadResult(value=[], write_success=False, reload_success=False, failure_reason=None, blocked_uids=[]) | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "insert_takeoffs_result without refresh|conflict": (
        "WriteReloadResult(value=[], write_success=False, reload_success=False, failure_reason=None, blocked_uids=[]) | "
        "calls=0 requests=['takeoffs_collection:7@7'] records=0 values=[None] verify=0 reloads=0 events=['SynchronizationConflictEvent']"
    ),
    "insert_takeoffs_result without refresh|unknown": (
        "WriteReloadResult(value=[], write_success=False, reload_success=False, failure_reason=None, blocked_uids=[]) | "
        "calls=1 requests=['takeoffs_collection:7@7'] records=3 values=[None] verify=0 reloads=0 events=[]"
    ),
    "insert_takeoffs_result without refresh|reload_failed": (
        "WriteReloadResult(value=['101', '102'], write_success=True, reload_success=True, failure_reason=None, blocked_uids=[]) | "
        "calls=1 requests=['takeoffs_collection:7@7'] records=3 values=[['101', '102']] verify=0 reloads=0 events=[]"
    ),
    "insert_takeoffs_result without refresh|other_database": (
        "WriteReloadResult(value=['101', '102'], write_success=True, reload_success=True, failure_reason=None, blocked_uids=[]) | "
        "calls=1 requests=['takeoffs_collection:7@7'] records=3 values=[['101', '102']] verify=0 reloads=0 events=[]"
    ),
    "insert_takeoffs_result without refresh|equivalent_path": (
        "WriteReloadResult(value=['101', '102'], write_success=True, reload_success=True, failure_reason=None, blocked_uids=[]) | "
        "calls=1 requests=['takeoffs_collection:7@7'] records=3 values=[['101', '102']] verify=0 reloads=0 events=[]"
    ),
    "insert_takeoffs_result consistency|failure": (
        "'raised RuntimeError: The takeoff insertion returned an incomplete authoritative identity set.' | "
        "calls=1 requests=['condition:10@7,page:21@7,takeoffs_collection:7@7'] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "insert_takeoffs_result consistency|denied": (
        "WriteReloadResult(value=[], write_success=False, reload_success=False, failure_reason=None, blocked_uids=[]) | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "insert_takeoffs_result consistency|locked": (
        "WriteReloadResult(value=[], write_success=False, reload_success=False, failure_reason=None, blocked_uids=[]) | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "insert_takeoffs_result consistency|conflict": (
        "WriteReloadResult(value=[], write_success=False, reload_success=False, failure_reason=None, blocked_uids=[]) | "
        "calls=0 requests=['condition:10@7,page:21@7,takeoffs_collection:7@7'] records=0 values=[None] verify=0 reloads=0 events=['SynchronizationConflictEvent']"
    ),
    "insert_takeoffs_result consistency|unknown": (
        "WriteReloadResult(value=[], write_success=False, reload_success=False, failure_reason=None, blocked_uids=[]) | "
        "calls=1 requests=['condition:10@7,page:21@7,takeoffs_collection:7@7'] records=3 values=[None] verify=0 reloads=0 events=[]"
    ),
    "insert_takeoffs_result consistency|reload_failed": (
        "WriteReloadResult(value=['101', '102'], write_success=True, reload_success=False, failure_reason=None, blocked_uids=[]) | "
        "calls=1 requests=['condition:10@7,page:21@7,takeoffs_collection:7@7'] records=3 values=[['101', '102']] verify=0 reloads=1 events=[]"
    ),
    "insert_takeoffs_result consistency|other_database": (
        "WriteReloadResult(value=['101', '102'], write_success=True, reload_success=True, failure_reason=None, blocked_uids=[]) | "
        "calls=1 requests=['condition:10@7,page:21@7,takeoffs_collection:7@7'] records=3 values=[['101', '102']] verify=0 reloads=1 events=['DatabaseRefreshedEvent']"
    ),
    "insert_takeoffs_result consistency|equivalent_path": (
        "WriteReloadResult(value=['101', '102'], write_success=True, reload_success=True, failure_reason=None, blocked_uids=[]) | "
        "calls=1 requests=['condition:10@7,page:21@7,takeoffs_collection:7@7'] records=3 values=[['101', '102']] verify=0 reloads=1 events=['DatabaseRefreshedEvent']"
    ),
    "insert_takeoffs empty|failure": ("no use case is reached"),
    "insert_takeoffs empty|denied": (
        "[] | " "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "insert_takeoffs empty|locked": (
        "[] | " "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "insert_takeoffs empty|conflict": (
        "[] | " "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "insert_takeoffs empty|unknown": (
        "[] | " "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "insert_takeoffs empty|reload_failed": (
        "[] | " "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "insert_takeoffs empty|other_database": (
        "[] | " "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "insert_takeoffs empty|equivalent_path": (
        "[] | " "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "delete_projects empty|failure": ("no use case is reached"),
    "delete_projects empty|denied": (
        "True | " "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "delete_projects empty|locked": (
        "True | " "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "delete_projects empty|conflict": (
        "True | " "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "delete_projects empty|unknown": (
        "True | " "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "delete_projects empty|reload_failed": (
        "True | " "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "delete_projects empty|other_database": (
        "True | " "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "delete_projects empty|equivalent_path": (
        "True | " "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "move_bids empty|failure": ("no use case is reached"),
    "move_bids empty|denied": (
        "True | " "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "move_bids empty|locked": (
        "True | " "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "move_bids empty|conflict": (
        "True | " "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "move_bids empty|unknown": (
        "True | " "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "move_bids empty|reload_failed": (
        "True | " "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "move_bids empty|other_database": (
        "True | " "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "move_bids empty|equivalent_path": (
        "True | " "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "delete_conditions empty|failure": ("no use case is reached"),
    "delete_conditions empty|denied": (
        "True | " "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "delete_conditions empty|locked": (
        "True | " "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "delete_conditions empty|conflict": (
        "True | " "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "delete_conditions empty|unknown": (
        "True | " "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "delete_conditions empty|reload_failed": (
        "True | " "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "delete_conditions empty|other_database": (
        "True | " "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "delete_conditions empty|equivalent_path": (
        "True | " "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "delete_conditions without bid|failure": (
        "False | "
        "calls=1 requests=['conditions_collection:unknown@None'] records=0 values=[False] verify=0 reloads=0 events=[]"
    ),
    "delete_conditions without bid|denied": (
        "False | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "delete_conditions without bid|locked": (
        "True | "
        "calls=1 requests=['conditions_collection:unknown@None'] records=2 values=[True] verify=0 reloads=1 events=['ConditionsChangedEvent']"
    ),
    "delete_conditions without bid|conflict": (
        "False | "
        "calls=0 requests=['conditions_collection:unknown@None'] records=0 values=[None] verify=0 reloads=0 events=['SynchronizationConflictEvent']"
    ),
    "delete_conditions without bid|unknown": (
        "False | "
        "calls=1 requests=['conditions_collection:unknown@None'] records=2 values=[None] verify=0 reloads=0 events=[]"
    ),
    "delete_conditions without bid|reload_failed": (
        "False | "
        "calls=1 requests=['conditions_collection:unknown@None'] records=2 values=[True] verify=0 reloads=1 events=[]"
    ),
    "delete_conditions without bid|other_database": (
        "True | "
        "calls=1 requests=['conditions_collection:unknown@None'] records=2 values=[True] verify=0 reloads=1 events=['ConditionsChangedEvent']"
    ),
    "delete_conditions without bid|equivalent_path": (
        "True | "
        "calls=1 requests=['conditions_collection:unknown@None'] records=2 values=[True] verify=0 reloads=1 events=['ConditionsChangedEvent']"
    ),
    "renumber_conditions empty|failure": ("no use case is reached"),
    "renumber_conditions empty|denied": (
        "True | " "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "renumber_conditions empty|locked": (
        "True | " "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "renumber_conditions empty|conflict": (
        "True | " "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "renumber_conditions empty|unknown": (
        "True | " "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "renumber_conditions empty|reload_failed": (
        "True | " "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "renumber_conditions empty|other_database": (
        "True | " "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "renumber_conditions empty|equivalent_path": (
        "True | " "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "save_takeoff_positions empty|failure": ("no use case is reached"),
    "save_takeoff_positions empty|denied": (
        "False | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "save_takeoff_positions empty|locked": (
        "False | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "save_takeoff_positions empty|conflict": (
        "False | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "save_takeoff_positions empty|unknown": (
        "False | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "save_takeoff_positions empty|reload_failed": (
        "False | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "save_takeoff_positions empty|other_database": (
        "False | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "save_takeoff_positions empty|equivalent_path": (
        "False | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "save_takeoff_rotations empty|failure": ("no use case is reached"),
    "save_takeoff_rotations empty|denied": (
        "False | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "save_takeoff_rotations empty|locked": (
        "False | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "save_takeoff_rotations empty|conflict": (
        "False | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "save_takeoff_rotations empty|unknown": (
        "False | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "save_takeoff_rotations empty|reload_failed": (
        "False | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "save_takeoff_rotations empty|other_database": (
        "False | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "save_takeoff_rotations empty|equivalent_path": (
        "False | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "save_takeoff_text_properties empty|failure": ("no use case is reached"),
    "save_takeoff_text_properties empty|denied": (
        "False | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "save_takeoff_text_properties empty|locked": (
        "False | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "save_takeoff_text_properties empty|conflict": (
        "False | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "save_takeoff_text_properties empty|unknown": (
        "False | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "save_takeoff_text_properties empty|reload_failed": (
        "False | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "save_takeoff_text_properties empty|other_database": (
        "False | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "save_takeoff_text_properties empty|equivalent_path": (
        "False | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "save_takeoffs_area empty|failure": ("no use case is reached"),
    "save_takeoffs_area empty|denied": (
        "False | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "save_takeoffs_area empty|locked": (
        "False | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "save_takeoffs_area empty|conflict": (
        "False | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "save_takeoffs_area empty|unknown": (
        "False | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "save_takeoffs_area empty|reload_failed": (
        "False | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "save_takeoffs_area empty|other_database": (
        "False | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "save_takeoffs_area empty|equivalent_path": (
        "False | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "set_takeoffs_negative empty|failure": ("no use case is reached"),
    "set_takeoffs_negative empty|denied": (
        "False | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "set_takeoffs_negative empty|locked": (
        "False | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "set_takeoffs_negative empty|conflict": (
        "False | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "set_takeoffs_negative empty|unknown": (
        "False | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "set_takeoffs_negative empty|reload_failed": (
        "False | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "set_takeoffs_negative empty|other_database": (
        "False | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "set_takeoffs_negative empty|equivalent_path": (
        "False | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "delete_takeoffs empty|failure": ("no use case is reached"),
    "delete_takeoffs empty|denied": (
        "False | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "delete_takeoffs empty|locked": (
        "False | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "delete_takeoffs empty|conflict": (
        "False | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "delete_takeoffs empty|unknown": (
        "False | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "delete_takeoffs empty|reload_failed": (
        "False | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "delete_takeoffs empty|other_database": (
        "False | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "delete_takeoffs empty|equivalent_path": (
        "False | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "save_takeoffs_condition empty|failure": ("no use case is reached"),
    "save_takeoffs_condition empty|denied": (
        "False | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "save_takeoffs_condition empty|locked": (
        "False | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "save_takeoffs_condition empty|conflict": (
        "False | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "save_takeoffs_condition empty|unknown": (
        "False | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "save_takeoffs_condition empty|reload_failed": (
        "False | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "save_takeoffs_condition empty|other_database": (
        "False | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "save_takeoffs_condition empty|equivalent_path": (
        "False | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "save_page_scales empty|failure": ("no use case is reached"),
    "save_page_scales empty|denied": (
        "False | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "save_page_scales empty|locked": (
        "False | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "save_page_scales empty|conflict": (
        "False | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "save_page_scales empty|unknown": (
        "False | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "save_page_scales empty|reload_failed": (
        "False | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "save_page_scales empty|other_database": (
        "False | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "save_page_scales empty|equivalent_path": (
        "False | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "save_page_image_adjustments empty|failure": ("no use case is reached"),
    "save_page_image_adjustments empty|denied": (
        "False | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "save_page_image_adjustments empty|locked": (
        "False | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "save_page_image_adjustments empty|conflict": (
        "False | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "save_page_image_adjustments empty|unknown": (
        "False | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "save_page_image_adjustments empty|reload_failed": (
        "False | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "save_page_image_adjustments empty|other_database": (
        "False | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "save_page_image_adjustments empty|equivalent_path": (
        "False | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "delete_pages empty|failure": ("no use case is reached"),
    "delete_pages empty|denied": (
        "False | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "delete_pages empty|locked": (
        "False | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "delete_pages empty|conflict": (
        "False | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "delete_pages empty|unknown": (
        "False | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "delete_pages empty|reload_failed": (
        "False | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "delete_pages empty|other_database": (
        "False | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "delete_pages empty|equivalent_path": (
        "False | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "delete_layers empty|failure": ("no use case is reached"),
    "delete_layers empty|denied": (
        "BatchWriteResult(requested_uids=[], succeeded_uids=[], failed_uids=[], reload_success=False) | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "delete_layers empty|locked": (
        "BatchWriteResult(requested_uids=[], succeeded_uids=[], failed_uids=[], reload_success=False) | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "delete_layers empty|conflict": (
        "BatchWriteResult(requested_uids=[], succeeded_uids=[], failed_uids=[], reload_success=False) | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "delete_layers empty|unknown": (
        "BatchWriteResult(requested_uids=[], succeeded_uids=[], failed_uids=[], reload_success=False) | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "delete_layers empty|reload_failed": (
        "BatchWriteResult(requested_uids=[], succeeded_uids=[], failed_uids=[], reload_success=False) | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "delete_layers empty|other_database": (
        "BatchWriteResult(requested_uids=[], succeeded_uids=[], failed_uids=[], reload_success=False) | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "delete_layers empty|equivalent_path": (
        "BatchWriteResult(requested_uids=[], succeeded_uids=[], failed_uids=[], reload_success=False) | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "delete_default_layers empty|failure": ("no use case is reached"),
    "delete_default_layers empty|denied": (
        "BatchWriteResult(requested_uids=[], succeeded_uids=[], failed_uids=[], reload_success=False) | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "delete_default_layers empty|locked": (
        "BatchWriteResult(requested_uids=[], succeeded_uids=[], failed_uids=[], reload_success=False) | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "delete_default_layers empty|conflict": (
        "BatchWriteResult(requested_uids=[], succeeded_uids=[], failed_uids=[], reload_success=False) | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "delete_default_layers empty|unknown": (
        "BatchWriteResult(requested_uids=[], succeeded_uids=[], failed_uids=[], reload_success=False) | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "delete_default_layers empty|reload_failed": (
        "BatchWriteResult(requested_uids=[], succeeded_uids=[], failed_uids=[], reload_success=False) | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "delete_default_layers empty|other_database": (
        "BatchWriteResult(requested_uids=[], succeeded_uids=[], failed_uids=[], reload_success=False) | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "delete_default_layers empty|equivalent_path": (
        "BatchWriteResult(requested_uids=[], succeeded_uids=[], failed_uids=[], reload_success=False) | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "update_all_layers_show without layer uids|failure": (
        "False | "
        "calls=1 requests=['layers_collection:7@7'] records=0 values=[False] verify=0 reloads=0 events=[]"
    ),
    "update_all_layers_show without layer uids|denied": (
        "False | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "update_all_layers_show without layer uids|locked": (
        "False | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "update_all_layers_show without layer uids|conflict": (
        "False | "
        "calls=0 requests=['layers_collection:7@7'] records=0 values=[None] verify=0 reloads=0 events=['SynchronizationConflictEvent']"
    ),
    "update_all_layers_show without layer uids|unknown": (
        "False | "
        "calls=1 requests=['layers_collection:7@7'] records=1 values=[None] verify=0 reloads=0 events=[]"
    ),
    "update_all_layers_show without layer uids|reload_failed": (
        "False | "
        "calls=1 requests=['layers_collection:7@7'] records=1 values=[True] verify=0 reloads=1 events=[]"
    ),
    "update_all_layers_show without layer uids|other_database": (
        "True | "
        "calls=1 requests=['layers_collection:7@7'] records=1 values=[True] verify=0 reloads=1 events=['DatabaseRefreshedEvent']"
    ),
    "update_all_layers_show without layer uids|equivalent_path": (
        "True | "
        "calls=1 requests=['layers_collection:7@7'] records=1 values=[True] verify=0 reloads=1 events=['DatabaseRefreshedEvent']"
    ),
    "update_condition|failure": (
        "\"raised AttributeError: 'bool' object has no attribute 'success'\" | "
        "calls=1 requests=['condition:c1@7'] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "update_condition|denied": (
        "UpdateConditionResultDto(success=False, error='The condition update could not be completed', error_presented=False) | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "update_condition|locked": (
        "UpdateConditionResultDto(success=False, error='The active bid is locked', error_presented=False) | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "update_condition|conflict": (
        "UpdateConditionResultDto(success=False, error='stale', error_presented=False) | "
        "calls=0 requests=['condition:c1@7'] records=0 values=[None] verify=0 reloads=0 events=['SynchronizationConflictEvent']"
    ),
    "update_condition|unknown": (
        "UpdateConditionResultDto(success=False, error='The condition update could not be completed', error_presented=False) | "
        "calls=1 requests=['condition:c1@7'] records=1 values=[None] verify=0 reloads=0 events=[]"
    ),
    "update_condition|reload_failed": (
        "UpdateConditionResultDto(success=False, error='Database reload failed after saving condition', error_presented=False) | "
        "calls=1 requests=['condition:c1@7'] records=1 values=[UpdateConditionResultDto(success=False, error='Database reload failed after saving condition', error_presented=False)] verify=0 reloads=1 events=[]"
    ),
    "update_condition|other_database": (
        "UpdateConditionResultDto(success=True, error=None, error_presented=False) | "
        "calls=1 requests=['condition:c1@7'] records=1 values=[UpdateConditionResultDto(success=True, error=None, error_presented=False)] verify=0 reloads=1 events=['ConditionsChangedEvent']"
    ),
    "update_condition|equivalent_path": (
        "UpdateConditionResultDto(success=True, error=None, error_presented=False) | "
        "calls=1 requests=['condition:c1@7'] records=1 values=[UpdateConditionResultDto(success=True, error=None, error_presented=False)] verify=0 reloads=1 events=['ConditionsChangedEvent']"
    ),
    "create_condition_result|failure": (
        "CreateConditionResult(value=None, write_success=False, reload_success=False, failure_reason=None, blocked_uids=[], projection=None) | "
        "calls=1 requests=['conditions_collection:7@7'] records=0 values=[None] verify=0 reloads=0 events=[]"
    ),
    "create_condition_result|denied": (
        "CreateConditionResult(value=None, write_success=False, reload_success=False, failure_reason=None, blocked_uids=[], projection=None) | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "create_condition_result|locked": (
        "CreateConditionResult(value=None, write_success=False, reload_success=False, failure_reason=None, blocked_uids=[], projection=None) | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "create_condition_result|conflict": (
        "CreateConditionResult(value=None, write_success=False, reload_success=False, failure_reason=None, blocked_uids=[], projection=None) | "
        "calls=0 requests=['conditions_collection:7@7'] records=0 values=[None] verify=0 reloads=0 events=['SynchronizationConflictEvent']"
    ),
    "create_condition_result|unknown": (
        "CreateConditionResult(value=None, write_success=False, reload_success=False, failure_reason=None, blocked_uids=[], projection=None) | "
        "calls=1 requests=['conditions_collection:7@7'] records=2 values=[None] verify=0 reloads=0 events=[]"
    ),
    "create_condition_result|reload_failed": (
        "CreateConditionResult(value='c9', write_success=True, reload_success=False, failure_reason=None, blocked_uids=[], projection=None) | "
        "calls=1 requests=['conditions_collection:7@7'] records=2 values=['c9'] verify=0 reloads=1 events=[]"
    ),
    "create_condition_result|other_database": (
        "CreateConditionResult(value='c9', write_success=True, reload_success=True, failure_reason=None, blocked_uids=[], projection=None) | "
        "calls=1 requests=['conditions_collection:7@7'] records=2 values=['c9'] verify=0 reloads=1 events=['ConditionsChangedEvent']"
    ),
    "create_condition_result|equivalent_path": (
        "CreateConditionResult(value='c9', write_success=True, reload_success=True, failure_reason=None, blocked_uids=[], projection=None) | "
        "calls=1 requests=['conditions_collection:7@7'] records=2 values=['c9'] verify=0 reloads=1 events=['ConditionsChangedEvent']"
    ),
    "delete_condition_folders_result|failure": (
        "WriteReloadResult(value=['f1', 'f2'], write_success=False, reload_success=False, failure_reason=None, blocked_uids=[]) | "
        "calls=1 requests=['conditions_collection:7@7'] records=0 values=[False] verify=0 reloads=0 events=[]"
    ),
    "delete_condition_folders_result|denied": (
        "WriteReloadResult(value=['f1', 'f2'], write_success=False, reload_success=False, failure_reason=None, blocked_uids=[]) | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "delete_condition_folders_result|locked": (
        "WriteReloadResult(value=None, write_success=False, reload_success=False, failure_reason=None, blocked_uids=[]) | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "delete_condition_folders_result|conflict": (
        "WriteReloadResult(value=['f1', 'f2'], write_success=False, reload_success=False, failure_reason=None, blocked_uids=[]) | "
        "calls=0 requests=['conditions_collection:7@7'] records=0 values=[None] verify=0 reloads=0 events=['SynchronizationConflictEvent']"
    ),
    "delete_condition_folders_result|unknown": (
        "WriteReloadResult(value=['f1', 'f2'], write_success=False, reload_success=False, failure_reason=None, blocked_uids=[]) | "
        "calls=1 requests=['conditions_collection:7@7'] records=3 values=[None] verify=0 reloads=0 events=[]"
    ),
    "delete_condition_folders_result|reload_failed": (
        "WriteReloadResult(value=['f1', 'f2'], write_success=True, reload_success=False, failure_reason=None, blocked_uids=[]) | "
        "calls=1 requests=['conditions_collection:7@7'] records=3 values=[True] verify=0 reloads=1 events=[]"
    ),
    "delete_condition_folders_result|other_database": (
        "WriteReloadResult(value=['f1', 'f2'], write_success=True, reload_success=True, failure_reason=None, blocked_uids=[]) | "
        "calls=1 requests=['conditions_collection:7@7'] records=3 values=[True] verify=0 reloads=1 events=['ConditionsChangedEvent']"
    ),
    "delete_condition_folders_result|equivalent_path": (
        "WriteReloadResult(value=['f1', 'f2'], write_success=True, reload_success=True, failure_reason=None, blocked_uids=[]) | "
        "calls=1 requests=['conditions_collection:7@7'] records=3 values=[True] verify=0 reloads=1 events=['ConditionsChangedEvent']"
    ),
    "delete_condition_folders|failure": (
        "False | "
        "calls=1 requests=['conditions_collection:7@7'] records=0 values=[False] verify=0 reloads=0 events=[]"
    ),
    "delete_condition_folders|denied": (
        "False | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "delete_condition_folders|locked": (
        "False | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "delete_condition_folders|conflict": (
        "False | "
        "calls=0 requests=['conditions_collection:7@7'] records=0 values=[None] verify=0 reloads=0 events=['SynchronizationConflictEvent']"
    ),
    "delete_condition_folders|unknown": (
        "False | "
        "calls=1 requests=['conditions_collection:7@7'] records=2 values=[None] verify=0 reloads=0 events=[]"
    ),
    "delete_condition_folders|reload_failed": (
        "False | "
        "calls=1 requests=['conditions_collection:7@7'] records=2 values=[True] verify=0 reloads=1 events=[]"
    ),
    "delete_condition_folders|other_database": (
        "True | "
        "calls=1 requests=['conditions_collection:7@7'] records=2 values=[True] verify=0 reloads=1 events=['ConditionsChangedEvent']"
    ),
    "delete_condition_folders|equivalent_path": (
        "True | "
        "calls=1 requests=['conditions_collection:7@7'] records=2 values=[True] verify=0 reloads=1 events=['ConditionsChangedEvent']"
    ),
    "save_condition_types_result|failure": (
        "WriteReloadResult(value=None, write_success=False, reload_success=False, failure_reason=None, blocked_uids=[]) | "
        "calls=1 requests=['condition_types_collection:database@None'] records=0 values=[None] verify=0 reloads=0 events=[]"
    ),
    "save_condition_types_result|denied": (
        "WriteReloadResult(value=None, write_success=False, reload_success=False, failure_reason=None, blocked_uids=[]) | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "save_condition_types_result|locked": (
        "WriteReloadResult(value={'n': '11'}, write_success=True, reload_success=True, failure_reason=None, blocked_uids=[]) | "
        "calls=1 requests=['condition_types_collection:database@None'] records=1 values=[{'n': '11'}] verify=0 reloads=1 events=['ConditionsChangedEvent']"
    ),
    "save_condition_types_result|conflict": (
        "WriteReloadResult(value=None, write_success=False, reload_success=False, failure_reason=None, blocked_uids=[]) | "
        "calls=0 requests=['condition_types_collection:database@None'] records=0 values=[None] verify=0 reloads=0 events=['SynchronizationConflictEvent']"
    ),
    "save_condition_types_result|unknown": (
        "WriteReloadResult(value=None, write_success=False, reload_success=False, failure_reason=None, blocked_uids=[]) | "
        "calls=1 requests=['condition_types_collection:database@None'] records=1 values=[None] verify=0 reloads=0 events=[]"
    ),
    "save_condition_types_result|reload_failed": (
        "WriteReloadResult(value={'n': '11'}, write_success=True, reload_success=False, failure_reason=None, blocked_uids=[]) | "
        "calls=1 requests=['condition_types_collection:database@None'] records=1 values=[{'n': '11'}] verify=0 reloads=1 events=[]"
    ),
    "save_condition_types_result|other_database": (
        "WriteReloadResult(value={'n': '11'}, write_success=True, reload_success=True, failure_reason=None, blocked_uids=[]) | "
        "calls=1 requests=['condition_types_collection:database@None'] records=1 values=[{'n': '11'}] verify=0 reloads=1 events=[]"
    ),
    "save_condition_types_result|equivalent_path": (
        "WriteReloadResult(value={'n': '11'}, write_success=True, reload_success=True, failure_reason=None, blocked_uids=[]) | "
        "calls=1 requests=['condition_types_collection:database@None'] records=1 values=[{'n': '11'}] verify=0 reloads=1 events=['ConditionsChangedEvent']"
    ),
    "save_condition_types_result partially blocked|failure": (
        "WriteReloadResult(value=None, write_success=False, reload_success=False, failure_reason='condition_type_in_use', blocked_uids=['used']) | "
        "calls=1 requests=['condition_types_collection:database@None'] records=0 values=[None] verify=0 reloads=0 events=[]"
    ),
    "save_condition_types_result partially blocked|denied": (
        "WriteReloadResult(value=None, write_success=False, reload_success=False, failure_reason='condition_type_in_use', blocked_uids=['used']) | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "save_condition_types_result partially blocked|locked": (
        "WriteReloadResult(value={}, write_success=True, reload_success=True, failure_reason='condition_type_in_use', blocked_uids=['used']) | "
        "calls=1 requests=['condition_types_collection:database@None'] records=1 values=[{}] verify=0 reloads=1 events=['ConditionsChangedEvent']"
    ),
    "save_condition_types_result partially blocked|conflict": (
        "WriteReloadResult(value=None, write_success=False, reload_success=False, failure_reason='condition_type_in_use', blocked_uids=['used']) | "
        "calls=0 requests=['condition_types_collection:database@None'] records=0 values=[None] verify=0 reloads=0 events=['SynchronizationConflictEvent']"
    ),
    "save_condition_types_result partially blocked|unknown": (
        "WriteReloadResult(value=None, write_success=False, reload_success=False, failure_reason='condition_type_in_use', blocked_uids=['used']) | "
        "calls=1 requests=['condition_types_collection:database@None'] records=1 values=[None] verify=0 reloads=0 events=[]"
    ),
    "save_condition_types_result partially blocked|reload_failed": (
        "WriteReloadResult(value={}, write_success=True, reload_success=False, failure_reason='condition_type_in_use', blocked_uids=['used']) | "
        "calls=1 requests=['condition_types_collection:database@None'] records=1 values=[{}] verify=0 reloads=1 events=[]"
    ),
    "save_condition_types_result partially blocked|other_database": (
        "WriteReloadResult(value={}, write_success=True, reload_success=True, failure_reason='condition_type_in_use', blocked_uids=['used']) | "
        "calls=1 requests=['condition_types_collection:database@None'] records=1 values=[{}] verify=0 reloads=1 events=[]"
    ),
    "save_condition_types_result partially blocked|equivalent_path": (
        "WriteReloadResult(value={}, write_success=True, reload_success=True, failure_reason='condition_type_in_use', blocked_uids=['used']) | "
        "calls=1 requests=['condition_types_collection:database@None'] records=1 values=[{}] verify=0 reloads=1 events=['ConditionsChangedEvent']"
    ),
    "save_condition_types_result blocked|failure": ("no use case is reached"),
    "save_condition_types_result blocked|denied": (
        "WriteReloadResult(value=None, write_success=False, reload_success=False, failure_reason='condition_type_in_use', blocked_uids=['used']) | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "save_condition_types_result blocked|locked": (
        "WriteReloadResult(value=None, write_success=False, reload_success=False, failure_reason='condition_type_in_use', blocked_uids=['used']) | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "save_condition_types_result blocked|conflict": (
        "WriteReloadResult(value=None, write_success=False, reload_success=False, failure_reason='condition_type_in_use', blocked_uids=['used']) | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "save_condition_types_result blocked|unknown": (
        "WriteReloadResult(value=None, write_success=False, reload_success=False, failure_reason='condition_type_in_use', blocked_uids=['used']) | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "save_condition_types_result blocked|reload_failed": (
        "WriteReloadResult(value=None, write_success=False, reload_success=False, failure_reason='condition_type_in_use', blocked_uids=['used']) | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "save_condition_types_result blocked|other_database": (
        "WriteReloadResult(value=None, write_success=False, reload_success=False, failure_reason='condition_type_in_use', blocked_uids=['used']) | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "save_condition_types_result blocked|equivalent_path": (
        "WriteReloadResult(value=None, write_success=False, reload_success=False, failure_reason='condition_type_in_use', blocked_uids=['used']) | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "save_condition_types_result without refresh|failure": (
        "WriteReloadResult(value=None, write_success=False, reload_success=False, failure_reason=None, blocked_uids=[]) | "
        "calls=1 requests=['condition_types_collection:database@None'] records=0 values=[None] verify=0 reloads=0 events=[]"
    ),
    "save_condition_types_result without refresh|denied": (
        "WriteReloadResult(value=None, write_success=False, reload_success=False, failure_reason=None, blocked_uids=[]) | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "save_condition_types_result without refresh|locked": (
        "WriteReloadResult(value={'n': '11'}, write_success=True, reload_success=True, failure_reason=None, blocked_uids=[]) | "
        "calls=1 requests=['condition_types_collection:database@None'] records=1 values=[{'n': '11'}] verify=0 reloads=0 events=[]"
    ),
    "save_condition_types_result without refresh|conflict": (
        "WriteReloadResult(value=None, write_success=False, reload_success=False, failure_reason=None, blocked_uids=[]) | "
        "calls=0 requests=['condition_types_collection:database@None'] records=0 values=[None] verify=0 reloads=0 events=['SynchronizationConflictEvent']"
    ),
    "save_condition_types_result without refresh|unknown": (
        "WriteReloadResult(value=None, write_success=False, reload_success=False, failure_reason=None, blocked_uids=[]) | "
        "calls=1 requests=['condition_types_collection:database@None'] records=1 values=[None] verify=0 reloads=0 events=[]"
    ),
    "save_condition_types_result without refresh|reload_failed": (
        "WriteReloadResult(value={'n': '11'}, write_success=True, reload_success=True, failure_reason=None, blocked_uids=[]) | "
        "calls=1 requests=['condition_types_collection:database@None'] records=1 values=[{'n': '11'}] verify=0 reloads=0 events=[]"
    ),
    "save_condition_types_result without refresh|other_database": (
        "WriteReloadResult(value={'n': '11'}, write_success=True, reload_success=True, failure_reason=None, blocked_uids=[]) | "
        "calls=1 requests=['condition_types_collection:database@None'] records=1 values=[{'n': '11'}] verify=0 reloads=0 events=[]"
    ),
    "save_condition_types_result without refresh|equivalent_path": (
        "WriteReloadResult(value={'n': '11'}, write_success=True, reload_success=True, failure_reason=None, blocked_uids=[]) | "
        "calls=1 requests=['condition_types_collection:database@None'] records=1 values=[{'n': '11'}] verify=0 reloads=0 events=[]"
    ),
    "save_condition_types_result empty|failure": ("no use case is reached"),
    "save_condition_types_result empty|denied": (
        "WriteReloadResult(value={}, write_success=True, reload_success=True, failure_reason=None, blocked_uids=[]) | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "save_condition_types_result empty|locked": (
        "WriteReloadResult(value={}, write_success=True, reload_success=True, failure_reason=None, blocked_uids=[]) | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "save_condition_types_result empty|conflict": (
        "WriteReloadResult(value={}, write_success=True, reload_success=True, failure_reason=None, blocked_uids=[]) | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "save_condition_types_result empty|unknown": (
        "WriteReloadResult(value={}, write_success=True, reload_success=True, failure_reason=None, blocked_uids=[]) | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "save_condition_types_result empty|reload_failed": (
        "WriteReloadResult(value={}, write_success=True, reload_success=True, failure_reason=None, blocked_uids=[]) | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "save_condition_types_result empty|other_database": (
        "WriteReloadResult(value={}, write_success=True, reload_success=True, failure_reason=None, blocked_uids=[]) | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "save_condition_types_result empty|equivalent_path": (
        "WriteReloadResult(value={}, write_success=True, reload_success=True, failure_reason=None, blocked_uids=[]) | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "save_condition_types|failure": (
        "None | "
        "calls=1 requests=['condition_types_collection:database@None'] records=0 values=[None] verify=0 reloads=0 events=[]"
    ),
    "save_condition_types|denied": (
        "None | " "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "save_condition_types|locked": (
        "{'n': '11'} | "
        "calls=1 requests=['condition_types_collection:database@None'] records=1 values=[{'n': '11'}] verify=0 reloads=1 events=['ConditionsChangedEvent']"
    ),
    "save_condition_types|conflict": (
        "None | "
        "calls=0 requests=['condition_types_collection:database@None'] records=0 values=[None] verify=0 reloads=0 events=['SynchronizationConflictEvent']"
    ),
    "save_condition_types|unknown": (
        "None | "
        "calls=1 requests=['condition_types_collection:database@None'] records=1 values=[None] verify=0 reloads=0 events=[]"
    ),
    "save_condition_types|reload_failed": (
        "None | "
        "calls=1 requests=['condition_types_collection:database@None'] records=1 values=[{'n': '11'}] verify=0 reloads=1 events=[]"
    ),
    "save_condition_types|other_database": (
        "{'n': '11'} | "
        "calls=1 requests=['condition_types_collection:database@None'] records=1 values=[{'n': '11'}] verify=0 reloads=1 events=[]"
    ),
    "save_condition_types|equivalent_path": (
        "{'n': '11'} | "
        "calls=1 requests=['condition_types_collection:database@None'] records=1 values=[{'n': '11'}] verify=0 reloads=1 events=['ConditionsChangedEvent']"
    ),
    "delete_condition_types_result|failure": (
        "WriteReloadResult(value=None, write_success=False, reload_success=False, failure_reason=None, blocked_uids=[]) | "
        "calls=1 requests=['condition_types_collection:database@None'] records=0 values=[None] verify=0 reloads=0 events=[]"
    ),
    "delete_condition_types_result|denied": (
        "WriteReloadResult(value=None, write_success=False, reload_success=False, failure_reason=None, blocked_uids=[]) | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "delete_condition_types_result|locked": (
        "WriteReloadResult(value={}, write_success=True, reload_success=True, failure_reason=None, blocked_uids=[]) | "
        "calls=1 requests=['condition_types_collection:database@None'] records=1 values=[{}] verify=0 reloads=1 events=['ConditionsChangedEvent']"
    ),
    "delete_condition_types_result|conflict": (
        "WriteReloadResult(value=None, write_success=False, reload_success=False, failure_reason=None, blocked_uids=[]) | "
        "calls=0 requests=['condition_types_collection:database@None'] records=0 values=[None] verify=0 reloads=0 events=['SynchronizationConflictEvent']"
    ),
    "delete_condition_types_result|unknown": (
        "WriteReloadResult(value=None, write_success=False, reload_success=False, failure_reason=None, blocked_uids=[]) | "
        "calls=1 requests=['condition_types_collection:database@None'] records=1 values=[None] verify=0 reloads=0 events=[]"
    ),
    "delete_condition_types_result|reload_failed": (
        "WriteReloadResult(value={}, write_success=True, reload_success=False, failure_reason=None, blocked_uids=[]) | "
        "calls=1 requests=['condition_types_collection:database@None'] records=1 values=[{}] verify=0 reloads=1 events=[]"
    ),
    "delete_condition_types_result|other_database": (
        "WriteReloadResult(value={}, write_success=True, reload_success=True, failure_reason=None, blocked_uids=[]) | "
        "calls=1 requests=['condition_types_collection:database@None'] records=1 values=[{}] verify=0 reloads=1 events=[]"
    ),
    "delete_condition_types_result|equivalent_path": (
        "WriteReloadResult(value={}, write_success=True, reload_success=True, failure_reason=None, blocked_uids=[]) | "
        "calls=1 requests=['condition_types_collection:database@None'] records=1 values=[{}] verify=0 reloads=1 events=['ConditionsChangedEvent']"
    ),
    "save_bid_areas_result|failure": (
        "WriteReloadResult(value=None, write_success=False, reload_success=False, failure_reason=None, blocked_uids=[]) | "
        "calls=1 requests=['areas_collection:7@7'] records=0 values=[None] verify=0 reloads=0 events=[]"
    ),
    "save_bid_areas_result|denied": (
        "WriteReloadResult(value=None, write_success=False, reload_success=False, failure_reason=None, blocked_uids=[]) | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "save_bid_areas_result|locked": (
        "WriteReloadResult(value=None, write_success=False, reload_success=False, failure_reason=None, blocked_uids=[]) | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "save_bid_areas_result|conflict": (
        "WriteReloadResult(value=None, write_success=False, reload_success=False, failure_reason=None, blocked_uids=[]) | "
        "calls=0 requests=['areas_collection:7@7'] records=0 values=[None] verify=0 reloads=0 events=['SynchronizationConflictEvent']"
    ),
    "save_bid_areas_result|unknown": (
        "WriteReloadResult(value=None, write_success=False, reload_success=False, failure_reason=None, blocked_uids=[]) | "
        "calls=1 requests=['areas_collection:7@7'] records=4 values=[None] verify=0 reloads=0 events=[]"
    ),
    "save_bid_areas_result|reload_failed": (
        "WriteReloadResult(value={'new_0': '9'}, write_success=True, reload_success=False, failure_reason=None, blocked_uids=[]) | "
        "calls=1 requests=['areas_collection:7@7'] records=4 values=[{'new_0': '9'}] verify=0 reloads=1 events=['BidAreasDeletedEvent']"
    ),
    "save_bid_areas_result|other_database": (
        "WriteReloadResult(value={'new_0': '9'}, write_success=True, reload_success=True, failure_reason=None, blocked_uids=[]) | "
        "calls=1 requests=['areas_collection:7@7'] records=4 values=[{'new_0': '9'}] verify=0 reloads=1 events=['BidAreasDeletedEvent', 'DatabaseRefreshedEvent']"
    ),
    "save_bid_areas_result|equivalent_path": (
        "WriteReloadResult(value={'new_0': '9'}, write_success=True, reload_success=True, failure_reason=None, blocked_uids=[]) | "
        "calls=1 requests=['areas_collection:7@7'] records=4 values=[{'new_0': '9'}] verify=0 reloads=1 events=['BidAreasDeletedEvent', 'DatabaseRefreshedEvent']"
    ),
    "save_bid_areas_result without refresh|failure": (
        "WriteReloadResult(value=None, write_success=False, reload_success=False, failure_reason=None, blocked_uids=[]) | "
        "calls=1 requests=['areas_collection:7@7'] records=0 values=[None] verify=0 reloads=0 events=[]"
    ),
    "save_bid_areas_result without refresh|denied": (
        "WriteReloadResult(value=None, write_success=False, reload_success=False, failure_reason=None, blocked_uids=[]) | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "save_bid_areas_result without refresh|locked": (
        "WriteReloadResult(value=None, write_success=False, reload_success=False, failure_reason=None, blocked_uids=[]) | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "save_bid_areas_result without refresh|conflict": (
        "WriteReloadResult(value=None, write_success=False, reload_success=False, failure_reason=None, blocked_uids=[]) | "
        "calls=0 requests=['areas_collection:7@7'] records=0 values=[None] verify=0 reloads=0 events=['SynchronizationConflictEvent']"
    ),
    "save_bid_areas_result without refresh|unknown": (
        "WriteReloadResult(value=None, write_success=False, reload_success=False, failure_reason=None, blocked_uids=[]) | "
        "calls=1 requests=['areas_collection:7@7'] records=4 values=[None] verify=0 reloads=0 events=[]"
    ),
    "save_bid_areas_result without refresh|reload_failed": (
        "WriteReloadResult(value={'new_0': '9'}, write_success=True, reload_success=True, failure_reason=None, blocked_uids=[]) | "
        "calls=1 requests=['areas_collection:7@7'] records=4 values=[{'new_0': '9'}] verify=0 reloads=0 events=['BidAreasDeletedEvent']"
    ),
    "save_bid_areas_result without refresh|other_database": (
        "WriteReloadResult(value={'new_0': '9'}, write_success=True, reload_success=True, failure_reason=None, blocked_uids=[]) | "
        "calls=1 requests=['areas_collection:7@7'] records=4 values=[{'new_0': '9'}] verify=0 reloads=0 events=['BidAreasDeletedEvent']"
    ),
    "save_bid_areas_result without refresh|equivalent_path": (
        "WriteReloadResult(value={'new_0': '9'}, write_success=True, reload_success=True, failure_reason=None, blocked_uids=[]) | "
        "calls=1 requests=['areas_collection:7@7'] records=4 values=[{'new_0': '9'}] verify=0 reloads=0 events=['BidAreasDeletedEvent']"
    ),
    "save_bid_areas_result deletion only|failure": (
        "WriteReloadResult(value=None, write_success=False, reload_success=False, failure_reason=None, blocked_uids=[]) | "
        "calls=1 requests=['areas_collection:7@7'] records=0 values=[None] verify=0 reloads=0 events=[]"
    ),
    "save_bid_areas_result deletion only|denied": (
        "WriteReloadResult(value=None, write_success=False, reload_success=False, failure_reason=None, blocked_uids=[]) | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "save_bid_areas_result deletion only|locked": (
        "WriteReloadResult(value=None, write_success=False, reload_success=False, failure_reason=None, blocked_uids=[]) | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "save_bid_areas_result deletion only|conflict": (
        "WriteReloadResult(value=None, write_success=False, reload_success=False, failure_reason=None, blocked_uids=[]) | "
        "calls=0 requests=['areas_collection:7@7'] records=0 values=[None] verify=0 reloads=0 events=['SynchronizationConflictEvent']"
    ),
    "save_bid_areas_result deletion only|unknown": (
        "WriteReloadResult(value=None, write_success=False, reload_success=False, failure_reason=None, blocked_uids=[]) | "
        "calls=1 requests=['areas_collection:7@7'] records=2 values=[None] verify=0 reloads=0 events=[]"
    ),
    "save_bid_areas_result deletion only|reload_failed": (
        "WriteReloadResult(value={}, write_success=True, reload_success=False, failure_reason=None, blocked_uids=[]) | "
        "calls=1 requests=['areas_collection:7@7'] records=2 values=[{}] verify=0 reloads=1 events=['BidAreasDeletedEvent']"
    ),
    "save_bid_areas_result deletion only|other_database": (
        "WriteReloadResult(value={}, write_success=True, reload_success=True, failure_reason=None, blocked_uids=[]) | "
        "calls=1 requests=['areas_collection:7@7'] records=2 values=[{}] verify=0 reloads=1 events=['BidAreasDeletedEvent', 'DatabaseRefreshedEvent']"
    ),
    "save_bid_areas_result deletion only|equivalent_path": (
        "WriteReloadResult(value={}, write_success=True, reload_success=True, failure_reason=None, blocked_uids=[]) | "
        "calls=1 requests=['areas_collection:7@7'] records=2 values=[{}] verify=0 reloads=1 events=['BidAreasDeletedEvent', 'DatabaseRefreshedEvent']"
    ),
    "save_bid_areas_result unchanged|failure": (
        "WriteReloadResult(value=None, write_success=False, reload_success=False, failure_reason=None, blocked_uids=[]) | "
        "calls=1 requests=['areas_collection:7@7'] records=0 values=[False] verify=0 reloads=0 events=[]"
    ),
    "save_bid_areas_result unchanged|denied": (
        "WriteReloadResult(value=None, write_success=False, reload_success=False, failure_reason=None, blocked_uids=[]) | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "save_bid_areas_result unchanged|locked": (
        "WriteReloadResult(value=None, write_success=False, reload_success=False, failure_reason=None, blocked_uids=[]) | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "save_bid_areas_result unchanged|conflict": (
        "WriteReloadResult(value=None, write_success=False, reload_success=False, failure_reason=None, blocked_uids=[]) | "
        "calls=0 requests=['areas_collection:7@7'] records=0 values=[None] verify=0 reloads=0 events=['SynchronizationConflictEvent']"
    ),
    "save_bid_areas_result unchanged|unknown": (
        "WriteReloadResult(value=None, write_success=False, reload_success=False, failure_reason=None, blocked_uids=[]) | "
        "calls=1 requests=['areas_collection:7@7'] records=0 values=[None] verify=0 reloads=0 events=[]"
    ),
    "save_bid_areas_result unchanged|reload_failed": (
        "WriteReloadResult(value={}, write_success=True, reload_success=True, failure_reason=None, blocked_uids=[]) | "
        "calls=1 requests=['areas_collection:7@7'] records=0 values=[{}] verify=0 reloads=0 events=[]"
    ),
    "save_bid_areas_result unchanged|other_database": (
        "WriteReloadResult(value={}, write_success=True, reload_success=True, failure_reason=None, blocked_uids=[]) | "
        "calls=1 requests=['areas_collection:7@7'] records=0 values=[{}] verify=0 reloads=0 events=[]"
    ),
    "save_bid_areas_result unchanged|equivalent_path": (
        "WriteReloadResult(value={}, write_success=True, reload_success=True, failure_reason=None, blocked_uids=[]) | "
        "calls=1 requests=['areas_collection:7@7'] records=0 values=[{}] verify=0 reloads=0 events=[]"
    ),
    "save_bid_areas|failure": (
        "None | "
        "calls=1 requests=['areas_collection:7@7'] records=0 values=[None] verify=0 reloads=0 events=[]"
    ),
    "save_bid_areas|denied": (
        "None | " "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "save_bid_areas|locked": (
        "None | " "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "save_bid_areas|conflict": (
        "None | "
        "calls=0 requests=['areas_collection:7@7'] records=0 values=[None] verify=0 reloads=0 events=['SynchronizationConflictEvent']"
    ),
    "save_bid_areas|unknown": (
        "None | "
        "calls=1 requests=['areas_collection:7@7'] records=4 values=[None] verify=0 reloads=0 events=[]"
    ),
    "save_bid_areas|reload_failed": (
        "None | "
        "calls=1 requests=['areas_collection:7@7'] records=4 values=[{'new_0': '9'}] verify=0 reloads=1 events=['BidAreasDeletedEvent']"
    ),
    "save_bid_areas|other_database": (
        "{'new_0': '9'} | "
        "calls=1 requests=['areas_collection:7@7'] records=4 values=[{'new_0': '9'}] verify=0 reloads=1 events=['BidAreasDeletedEvent', 'DatabaseRefreshedEvent']"
    ),
    "save_bid_areas|equivalent_path": (
        "{'new_0': '9'} | "
        "calls=1 requests=['areas_collection:7@7'] records=4 values=[{'new_0': '9'}] verify=0 reloads=1 events=['BidAreasDeletedEvent', 'DatabaseRefreshedEvent']"
    ),
    "save_employees_result empty|failure": ("no use case is reached"),
    "save_employees_result empty|denied": (
        "WriteReloadResult(value={}, write_success=True, reload_success=True, failure_reason=None, blocked_uids=[]) | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "save_employees_result empty|locked": (
        "WriteReloadResult(value={}, write_success=True, reload_success=True, failure_reason=None, blocked_uids=[]) | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "save_employees_result empty|conflict": (
        "WriteReloadResult(value={}, write_success=True, reload_success=True, failure_reason=None, blocked_uids=[]) | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "save_employees_result empty|unknown": (
        "WriteReloadResult(value={}, write_success=True, reload_success=True, failure_reason=None, blocked_uids=[]) | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "save_employees_result empty|reload_failed": (
        "WriteReloadResult(value={}, write_success=True, reload_success=True, failure_reason=None, blocked_uids=[]) | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "save_employees_result empty|other_database": (
        "WriteReloadResult(value={}, write_success=True, reload_success=True, failure_reason=None, blocked_uids=[]) | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "save_employees_result empty|equivalent_path": (
        "WriteReloadResult(value={}, write_success=True, reload_success=True, failure_reason=None, blocked_uids=[]) | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "save_employees_result without refresh|failure": (
        "WriteReloadResult(value=None, write_success=False, reload_success=False, failure_reason=None, blocked_uids=[]) | "
        "calls=1 requests=['employees_collection:database@None'] records=0 values=[None] verify=0 reloads=0 events=[]"
    ),
    "save_employees_result without refresh|denied": (
        "WriteReloadResult(value=None, write_success=False, reload_success=False, failure_reason=None, blocked_uids=[]) | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "save_employees_result without refresh|locked": (
        "WriteReloadResult(value={'n': '6'}, write_success=True, reload_success=True, failure_reason=None, blocked_uids=[]) | "
        "calls=1 requests=['employees_collection:database@None'] records=1 values=[{'n': '6'}] verify=0 reloads=0 events=[]"
    ),
    "save_employees_result without refresh|conflict": (
        "WriteReloadResult(value=None, write_success=False, reload_success=False, failure_reason=None, blocked_uids=[]) | "
        "calls=0 requests=['employees_collection:database@None'] records=0 values=[None] verify=0 reloads=0 events=['SynchronizationConflictEvent']"
    ),
    "save_employees_result without refresh|unknown": (
        "WriteReloadResult(value=None, write_success=False, reload_success=False, failure_reason=None, blocked_uids=[]) | "
        "calls=1 requests=['employees_collection:database@None'] records=1 values=[None] verify=0 reloads=0 events=[]"
    ),
    "save_employees_result without refresh|reload_failed": (
        "WriteReloadResult(value={'n': '6'}, write_success=True, reload_success=True, failure_reason=None, blocked_uids=[]) | "
        "calls=1 requests=['employees_collection:database@None'] records=1 values=[{'n': '6'}] verify=0 reloads=0 events=[]"
    ),
    "save_employees_result without refresh|other_database": (
        "WriteReloadResult(value={'n': '6'}, write_success=True, reload_success=True, failure_reason=None, blocked_uids=[]) | "
        "calls=1 requests=['employees_collection:database@None'] records=1 values=[{'n': '6'}] verify=0 reloads=0 events=[]"
    ),
    "save_employees_result without refresh|equivalent_path": (
        "WriteReloadResult(value={'n': '6'}, write_success=True, reload_success=True, failure_reason=None, blocked_uids=[]) | "
        "calls=1 requests=['employees_collection:database@None'] records=1 values=[{'n': '6'}] verify=0 reloads=0 events=[]"
    ),
    "save_employees|failure": (
        "False | "
        "calls=1 requests=['employees_collection:database@None'] records=0 values=[None] verify=0 reloads=0 events=[]"
    ),
    "save_employees|denied": (
        "False | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "save_employees|locked": (
        "True | "
        "calls=1 requests=['employees_collection:database@None'] records=1 values=[{'n': '6'}] verify=0 reloads=1 events=['DatabaseRefreshedEvent']"
    ),
    "save_employees|conflict": (
        "False | "
        "calls=0 requests=['employees_collection:database@None'] records=0 values=[None] verify=0 reloads=0 events=['SynchronizationConflictEvent']"
    ),
    "save_employees|unknown": (
        "False | "
        "calls=1 requests=['employees_collection:database@None'] records=1 values=[None] verify=0 reloads=0 events=[]"
    ),
    "save_employees|reload_failed": (
        "False | "
        "calls=1 requests=['employees_collection:database@None'] records=1 values=[{'n': '6'}] verify=0 reloads=1 events=[]"
    ),
    "save_employees|other_database": (
        "True | "
        "calls=1 requests=['employees_collection:database@None'] records=1 values=[{'n': '6'}] verify=0 reloads=1 events=['DatabaseRefreshedEvent']"
    ),
    "save_employees|equivalent_path": (
        "True | "
        "calls=1 requests=['employees_collection:database@None'] records=1 values=[{'n': '6'}] verify=0 reloads=1 events=['DatabaseRefreshedEvent']"
    ),
    "save_pay_classes unchanged|failure": ("no use case is reached"),
    "save_pay_classes unchanged|denied": (
        "{} | " "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "save_pay_classes unchanged|locked": (
        "{} | " "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "save_pay_classes unchanged|conflict": (
        "{} | " "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "save_pay_classes unchanged|unknown": (
        "{} | " "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "save_pay_classes unchanged|reload_failed": (
        "{} | " "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "save_pay_classes unchanged|other_database": (
        "{} | " "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "save_pay_classes unchanged|equivalent_path": (
        "{} | " "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "save_takeoffs_condition|failure": (
        "False | "
        "calls=1 requests=['takeoff:30@7'] records=0 values=[False] verify=0 reloads=0 events=[]"
    ),
    "save_takeoffs_condition|denied": (
        "False | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "save_takeoffs_condition|locked": (
        "False | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "save_takeoffs_condition|conflict": (
        "False | "
        "calls=0 requests=['takeoff:30@7'] records=0 values=[None] verify=0 reloads=0 events=['SynchronizationConflictEvent']"
    ),
    "save_takeoffs_condition|unknown": (
        "False | "
        "calls=1 requests=['takeoff:30@7'] records=1 values=[None] verify=0 reloads=0 events=[]"
    ),
    "save_takeoffs_condition|reload_failed": (
        "False | "
        "calls=1 requests=['takeoff:30@7'] records=1 values=[True] verify=0 reloads=1 events=[]"
    ),
    "save_takeoffs_condition|other_database": (
        "False | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "save_takeoffs_condition|equivalent_path": (
        "True | "
        "calls=1 requests=['takeoff:30@7'] records=1 values=[True] verify=0 reloads=1 events=['DatabaseRefreshedEvent']"
    ),
    "save_takeoffs_condition without refresh|failure": (
        "False | "
        "calls=1 requests=['takeoff:30@7,takeoff:32@7'] records=0 values=[False] verify=0 reloads=0 events=[]"
    ),
    "save_takeoffs_condition without refresh|denied": (
        "False | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "save_takeoffs_condition without refresh|locked": (
        "False | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "save_takeoffs_condition without refresh|conflict": (
        "False | "
        "calls=0 requests=['takeoff:30@7,takeoff:32@7'] records=0 values=[None] verify=0 reloads=0 events=['SynchronizationConflictEvent']"
    ),
    "save_takeoffs_condition without refresh|unknown": (
        "False | "
        "calls=1 requests=['takeoff:30@7,takeoff:32@7'] records=2 values=[None] verify=0 reloads=0 events=[]"
    ),
    "save_takeoffs_condition without refresh|reload_failed": (
        "True | "
        "calls=1 requests=['takeoff:30@7,takeoff:32@7'] records=2 values=[True] verify=0 reloads=0 events=[]"
    ),
    "save_takeoffs_condition without refresh|other_database": (
        "False | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "save_takeoffs_condition without refresh|equivalent_path": (
        "True | "
        "calls=1 requests=['takeoff:30@7,takeoff:32@7'] records=2 values=[True] verify=0 reloads=0 events=[]"
    ),
    "duplicate_conditions_to_bid into the active bid|failure": (
        "{} | "
        "calls=1 requests=['conditions_collection:7@7'] records=0 values=[{}] verify=0 reloads=0 events=[]"
    ),
    "duplicate_conditions_to_bid into the active bid|denied": (
        "{} | " "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "duplicate_conditions_to_bid into the active bid|locked": (
        "{} | " "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "duplicate_conditions_to_bid into the active bid|conflict": (
        "{} | "
        "calls=0 requests=['conditions_collection:7@7'] records=0 values=[None] verify=0 reloads=0 events=['SynchronizationConflictEvent']"
    ),
    "duplicate_conditions_to_bid into the active bid|unknown": (
        "{} | "
        "calls=1 requests=['conditions_collection:7@7'] records=2 values=[None] verify=0 reloads=0 events=[]"
    ),
    "duplicate_conditions_to_bid into the active bid|reload_failed": (
        "{} | "
        "calls=1 requests=['conditions_collection:7@7'] records=2 values=[{'c1': 'c9'}] verify=0 reloads=1 events=[]"
    ),
    "duplicate_conditions_to_bid into the active bid|other_database": (
        "{'c1': 'c9'} | "
        "calls=1 requests=['conditions_collection:7@7'] records=2 values=[{'c1': 'c9'}] verify=0 reloads=1 events=['ConditionsChangedEvent']"
    ),
    "duplicate_conditions_to_bid into the active bid|equivalent_path": (
        "{'c1': 'c9'} | "
        "calls=1 requests=['conditions_collection:7@7'] records=2 values=[{'c1': 'c9'}] verify=0 reloads=1 events=['ConditionsChangedEvent']"
    ),
    "duplicate_conditions_to_bid without refresh|failure": (
        "{} | "
        "calls=1 requests=['conditions_collection:8@8'] records=0 values=[{}] verify=0 reloads=0 events=[]"
    ),
    "duplicate_conditions_to_bid without refresh|denied": (
        "{} | " "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "duplicate_conditions_to_bid without refresh|locked": (
        "{'c1': 'c9'} | "
        "calls=1 requests=['conditions_collection:8@8'] records=2 values=[{'c1': 'c9'}] verify=0 reloads=0 events=[]"
    ),
    "duplicate_conditions_to_bid without refresh|conflict": (
        "{} | "
        "calls=0 requests=['conditions_collection:8@8'] records=0 values=[None] verify=0 reloads=0 events=['SynchronizationConflictEvent']"
    ),
    "duplicate_conditions_to_bid without refresh|unknown": (
        "{} | "
        "calls=1 requests=['conditions_collection:8@8'] records=2 values=[None] verify=0 reloads=0 events=[]"
    ),
    "duplicate_conditions_to_bid without refresh|reload_failed": (
        "{'c1': 'c9'} | "
        "calls=1 requests=['conditions_collection:8@8'] records=2 values=[{'c1': 'c9'}] verify=0 reloads=0 events=[]"
    ),
    "duplicate_conditions_to_bid without refresh|other_database": (
        "{'c1': 'c9'} | "
        "calls=1 requests=['conditions_collection:8@8'] records=2 values=[{'c1': 'c9'}] verify=0 reloads=0 events=[]"
    ),
    "duplicate_conditions_to_bid without refresh|equivalent_path": (
        "{'c1': 'c9'} | "
        "calls=1 requests=['conditions_collection:8@8'] records=2 values=[{'c1': 'c9'}] verify=0 reloads=0 events=[]"
    ),
    "duplicate_conditions_to_bid empty map|failure": (
        "{} | "
        "calls=1 requests=['conditions_collection:8@8'] records=0 values=[{}] verify=0 reloads=0 events=[]"
    ),
    "duplicate_conditions_to_bid empty map|denied": (
        "{} | " "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "duplicate_conditions_to_bid empty map|locked": (
        "{} | "
        "calls=1 requests=['conditions_collection:8@8'] records=0 values=[{}] verify=0 reloads=0 events=[]"
    ),
    "duplicate_conditions_to_bid empty map|conflict": (
        "{} | "
        "calls=0 requests=['conditions_collection:8@8'] records=0 values=[None] verify=0 reloads=0 events=['SynchronizationConflictEvent']"
    ),
    "duplicate_conditions_to_bid empty map|unknown": (
        "{} | "
        "calls=1 requests=['conditions_collection:8@8'] records=0 values=[None] verify=0 reloads=0 events=[]"
    ),
    "duplicate_conditions_to_bid empty map|reload_failed": (
        "{} | "
        "calls=1 requests=['conditions_collection:8@8'] records=0 values=[{}] verify=0 reloads=0 events=[]"
    ),
    "duplicate_conditions_to_bid empty map|other_database": (
        "{} | "
        "calls=1 requests=['conditions_collection:8@8'] records=0 values=[{}] verify=0 reloads=0 events=[]"
    ),
    "duplicate_conditions_to_bid empty map|equivalent_path": (
        "{} | "
        "calls=1 requests=['conditions_collection:8@8'] records=0 values=[{}] verify=0 reloads=0 events=[]"
    ),
    "create_condition_result without bid|failure": (
        "\"raised ValueError: invalid literal for int() with base 10: ''\" | "
        "calls=1 requests=['conditions_collection:unknown@None'] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "create_condition_result without bid|denied": (
        "CreateConditionResult(value=None, write_success=False, reload_success=False, failure_reason=None, blocked_uids=[], projection=None) | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "create_condition_result without bid|locked": (
        "CreateConditionResult(value=None, write_success=False, reload_success=False, failure_reason=None, blocked_uids=[], projection=None) | "
        "calls=1 requests=['conditions_collection:unknown@None'] records=0 values=[None] verify=0 reloads=0 events=[]"
    ),
    "create_condition_result without bid|conflict": (
        "CreateConditionResult(value=None, write_success=False, reload_success=False, failure_reason=None, blocked_uids=[], projection=None) | "
        "calls=0 requests=['conditions_collection:unknown@None'] records=0 values=[None] verify=0 reloads=0 events=['SynchronizationConflictEvent']"
    ),
    "create_condition_result without bid|unknown": (
        "CreateConditionResult(value=None, write_success=False, reload_success=False, failure_reason=None, blocked_uids=[], projection=None) | "
        "calls=1 requests=['conditions_collection:unknown@None'] records=0 values=[None] verify=0 reloads=0 events=[]"
    ),
    "create_condition_result without bid|reload_failed": (
        "CreateConditionResult(value=None, write_success=False, reload_success=False, failure_reason=None, blocked_uids=[], projection=None) | "
        "calls=1 requests=['conditions_collection:unknown@None'] records=0 values=[None] verify=0 reloads=0 events=[]"
    ),
    "create_condition_result without bid|other_database": (
        "CreateConditionResult(value=None, write_success=False, reload_success=False, failure_reason=None, blocked_uids=[], projection=None) | "
        "calls=1 requests=['conditions_collection:unknown@None'] records=0 values=[None] verify=0 reloads=0 events=[]"
    ),
    "create_condition_result without bid|equivalent_path": (
        "CreateConditionResult(value=None, write_success=False, reload_success=False, failure_reason=None, blocked_uids=[], projection=None) | "
        "calls=1 requests=['conditions_collection:unknown@None'] records=0 values=[None] verify=0 reloads=0 events=[]"
    ),
    "delete_condition_folders_result without bid|failure": (
        "WriteReloadResult(value=['f1'], write_success=False, reload_success=False, failure_reason=None, blocked_uids=[]) | "
        "calls=1 requests=['conditions_collection:unknown@None'] records=0 values=[False] verify=0 reloads=0 events=[]"
    ),
    "delete_condition_folders_result without bid|denied": (
        "WriteReloadResult(value=['f1'], write_success=False, reload_success=False, failure_reason=None, blocked_uids=[]) | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "delete_condition_folders_result without bid|locked": (
        "WriteReloadResult(value=['f1'], write_success=True, reload_success=True, failure_reason=None, blocked_uids=[]) | "
        "calls=1 requests=['conditions_collection:unknown@None'] records=2 values=[True] verify=0 reloads=1 events=['ConditionsChangedEvent']"
    ),
    "delete_condition_folders_result without bid|conflict": (
        "WriteReloadResult(value=['f1'], write_success=False, reload_success=False, failure_reason=None, blocked_uids=[]) | "
        "calls=0 requests=['conditions_collection:unknown@None'] records=0 values=[None] verify=0 reloads=0 events=['SynchronizationConflictEvent']"
    ),
    "delete_condition_folders_result without bid|unknown": (
        "WriteReloadResult(value=['f1'], write_success=False, reload_success=False, failure_reason=None, blocked_uids=[]) | "
        "calls=1 requests=['conditions_collection:unknown@None'] records=2 values=[None] verify=0 reloads=0 events=[]"
    ),
    "delete_condition_folders_result without bid|reload_failed": (
        "WriteReloadResult(value=['f1'], write_success=True, reload_success=False, failure_reason=None, blocked_uids=[]) | "
        "calls=1 requests=['conditions_collection:unknown@None'] records=2 values=[True] verify=0 reloads=1 events=[]"
    ),
    "delete_condition_folders_result without bid|other_database": (
        "WriteReloadResult(value=['f1'], write_success=True, reload_success=True, failure_reason=None, blocked_uids=[]) | "
        "calls=1 requests=['conditions_collection:unknown@None'] records=2 values=[True] verify=0 reloads=1 events=['ConditionsChangedEvent']"
    ),
    "delete_condition_folders_result without bid|equivalent_path": (
        "WriteReloadResult(value=['f1'], write_success=True, reload_success=True, failure_reason=None, blocked_uids=[]) | "
        "calls=1 requests=['conditions_collection:unknown@None'] records=2 values=[True] verify=0 reloads=1 events=['ConditionsChangedEvent']"
    ),
    "delete_condition_folders_result empty|failure": ("no use case is reached"),
    "delete_condition_folders_result empty|denied": (
        "WriteReloadResult(value=[], write_success=True, reload_success=True, failure_reason=None, blocked_uids=[]) | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "delete_condition_folders_result empty|locked": (
        "WriteReloadResult(value=[], write_success=True, reload_success=True, failure_reason=None, blocked_uids=[]) | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "delete_condition_folders_result empty|conflict": (
        "WriteReloadResult(value=[], write_success=True, reload_success=True, failure_reason=None, blocked_uids=[]) | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "delete_condition_folders_result empty|unknown": (
        "WriteReloadResult(value=[], write_success=True, reload_success=True, failure_reason=None, blocked_uids=[]) | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "delete_condition_folders_result empty|reload_failed": (
        "WriteReloadResult(value=[], write_success=True, reload_success=True, failure_reason=None, blocked_uids=[]) | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "delete_condition_folders_result empty|other_database": (
        "WriteReloadResult(value=[], write_success=True, reload_success=True, failure_reason=None, blocked_uids=[]) | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "delete_condition_folders_result empty|equivalent_path": (
        "WriteReloadResult(value=[], write_success=True, reload_success=True, failure_reason=None, blocked_uids=[]) | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "insert_takeoffs_result empty|failure": ("no use case is reached"),
    "insert_takeoffs_result empty|denied": (
        "WriteReloadResult(value=[], write_success=True, reload_success=True, failure_reason=None, blocked_uids=[]) | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "insert_takeoffs_result empty|locked": (
        "WriteReloadResult(value=[], write_success=True, reload_success=True, failure_reason=None, blocked_uids=[]) | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "insert_takeoffs_result empty|conflict": (
        "WriteReloadResult(value=[], write_success=True, reload_success=True, failure_reason=None, blocked_uids=[]) | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "insert_takeoffs_result empty|unknown": (
        "WriteReloadResult(value=[], write_success=True, reload_success=True, failure_reason=None, blocked_uids=[]) | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "insert_takeoffs_result empty|reload_failed": (
        "WriteReloadResult(value=[], write_success=True, reload_success=True, failure_reason=None, blocked_uids=[]) | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "insert_takeoffs_result empty|other_database": (
        "WriteReloadResult(value=[], write_success=True, reload_success=True, failure_reason=None, blocked_uids=[]) | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "insert_takeoffs_result empty|equivalent_path": (
        "WriteReloadResult(value=[], write_success=True, reload_success=True, failure_reason=None, blocked_uids=[]) | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "save_bid_areas_result new only|failure": (
        "WriteReloadResult(value=None, write_success=False, reload_success=False, failure_reason=None, blocked_uids=[]) | "
        "calls=1 requests=['areas_collection:7@7'] records=0 values=[False] verify=0 reloads=0 events=[]"
    ),
    "save_bid_areas_result new only|denied": (
        "WriteReloadResult(value=None, write_success=False, reload_success=False, failure_reason=None, blocked_uids=[]) | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "save_bid_areas_result new only|locked": (
        "WriteReloadResult(value=None, write_success=False, reload_success=False, failure_reason=None, blocked_uids=[]) | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "save_bid_areas_result new only|conflict": (
        "WriteReloadResult(value=None, write_success=False, reload_success=False, failure_reason=None, blocked_uids=[]) | "
        "calls=0 requests=['areas_collection:7@7'] records=0 values=[None] verify=0 reloads=0 events=['SynchronizationConflictEvent']"
    ),
    "save_bid_areas_result new only|unknown": (
        "WriteReloadResult(value=None, write_success=False, reload_success=False, failure_reason=None, blocked_uids=[]) | "
        "calls=1 requests=['areas_collection:7@7'] records=2 values=[None] verify=0 reloads=0 events=[]"
    ),
    "save_bid_areas_result new only|reload_failed": (
        "WriteReloadResult(value={'new_0': '9'}, write_success=True, reload_success=False, failure_reason=None, blocked_uids=[]) | "
        "calls=1 requests=['areas_collection:7@7'] records=2 values=[{'new_0': '9'}] verify=0 reloads=1 events=[]"
    ),
    "save_bid_areas_result new only|other_database": (
        "WriteReloadResult(value={'new_0': '9'}, write_success=True, reload_success=True, failure_reason=None, blocked_uids=[]) | "
        "calls=1 requests=['areas_collection:7@7'] records=2 values=[{'new_0': '9'}] verify=0 reloads=1 events=['DatabaseRefreshedEvent']"
    ),
    "save_bid_areas_result new only|equivalent_path": (
        "WriteReloadResult(value={'new_0': '9'}, write_success=True, reload_success=True, failure_reason=None, blocked_uids=[]) | "
        "calls=1 requests=['areas_collection:7@7'] records=2 values=[{'new_0': '9'}] verify=0 reloads=1 events=['DatabaseRefreshedEvent']"
    ),
    "save_bid_areas_result updated only|failure": (
        "WriteReloadResult(value=None, write_success=False, reload_success=False, failure_reason=None, blocked_uids=[]) | "
        "calls=1 requests=['areas_collection:7@7'] records=0 values=[False] verify=0 reloads=0 events=[]"
    ),
    "save_bid_areas_result updated only|denied": (
        "WriteReloadResult(value=None, write_success=False, reload_success=False, failure_reason=None, blocked_uids=[]) | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "save_bid_areas_result updated only|locked": (
        "WriteReloadResult(value=None, write_success=False, reload_success=False, failure_reason=None, blocked_uids=[]) | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "save_bid_areas_result updated only|conflict": (
        "WriteReloadResult(value=None, write_success=False, reload_success=False, failure_reason=None, blocked_uids=[]) | "
        "calls=0 requests=['areas_collection:7@7'] records=0 values=[None] verify=0 reloads=0 events=['SynchronizationConflictEvent']"
    ),
    "save_bid_areas_result updated only|unknown": (
        "WriteReloadResult(value=None, write_success=False, reload_success=False, failure_reason=None, blocked_uids=[]) | "
        "calls=1 requests=['areas_collection:7@7'] records=2 values=[None] verify=0 reloads=0 events=[]"
    ),
    "save_bid_areas_result updated only|reload_failed": (
        "WriteReloadResult(value={}, write_success=True, reload_success=False, failure_reason=None, blocked_uids=[]) | "
        "calls=1 requests=['areas_collection:7@7'] records=2 values=[{}] verify=0 reloads=1 events=[]"
    ),
    "save_bid_areas_result updated only|other_database": (
        "WriteReloadResult(value={}, write_success=True, reload_success=True, failure_reason=None, blocked_uids=[]) | "
        "calls=1 requests=['areas_collection:7@7'] records=2 values=[{}] verify=0 reloads=1 events=['DatabaseRefreshedEvent']"
    ),
    "save_bid_areas_result updated only|equivalent_path": (
        "WriteReloadResult(value={}, write_success=True, reload_success=True, failure_reason=None, blocked_uids=[]) | "
        "calls=1 requests=['areas_collection:7@7'] records=2 values=[{}] verify=0 reloads=1 events=['DatabaseRefreshedEvent']"
    ),
    "duplicate_conditions_result reassign|failure": (
        "WriteReloadResult(value=[], write_success=False, reload_success=False, failure_reason='The condition duplicate returned an incomplete identity map.', blocked_uids=[]) | "
        "calls=1 requests=['condition:10@7,conditions_collection:7@7,page:20@7,takeoff:30@7,takeoff:31@7'] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "duplicate_conditions_result reassign|denied": (
        "WriteReloadResult(value=[], write_success=False, reload_success=False, failure_reason=None, blocked_uids=[]) | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "duplicate_conditions_result reassign|locked": (
        "WriteReloadResult(value=[], write_success=False, reload_success=False, failure_reason=None, blocked_uids=[]) | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "duplicate_conditions_result reassign|conflict": (
        "WriteReloadResult(value=[], write_success=False, reload_success=False, failure_reason=None, blocked_uids=[]) | "
        "calls=0 requests=['condition:10@7,conditions_collection:7@7,page:20@7,takeoff:30@7,takeoff:31@7'] records=0 values=[None] verify=0 reloads=0 events=['SynchronizationConflictEvent']"
    ),
    "duplicate_conditions_result reassign|unknown": (
        "WriteReloadResult(value=[], write_success=False, reload_success=False, failure_reason=None, blocked_uids=[]) | "
        "calls=2 requests=['condition:10@7,conditions_collection:7@7,page:20@7,takeoff:30@7,takeoff:31@7'] records=3 values=[None] verify=1 reloads=0 events=[]"
    ),
    "duplicate_conditions_result reassign|reload_failed": (
        "WriteReloadResult(value=['c9'], write_success=True, reload_success=False, failure_reason=None, blocked_uids=[]) | "
        "calls=2 requests=['condition:10@7,conditions_collection:7@7,page:20@7,takeoff:30@7,takeoff:31@7'] records=3 values=[('c9',)] verify=1 reloads=1 events=[]"
    ),
    "duplicate_conditions_result reassign|other_database": (
        "WriteReloadResult(value=[], write_success=False, reload_success=False, failure_reason='The property mutation no longer owns the current Bid.', blocked_uids=[]) | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "duplicate_conditions_result reassign|equivalent_path": (
        "WriteReloadResult(value=['c9'], write_success=True, reload_success=True, failure_reason=None, blocked_uids=[]) | "
        "calls=2 requests=['condition:10@7,conditions_collection:7@7,page:20@7,takeoff:30@7,takeoff:31@7'] records=3 values=[('c9',)] verify=1 reloads=1 events=['ConditionsChangedEvent']"
    ),
}
_PLAN_LOCAL_SCENARIO_EXPECTED = {
    "delete_local mixed|failure": (
        "outcome=failed_before_commit message='The annotation deletion was incomplete.' commit=False tokens=() conflict=no authoritative=no created=() | "
        "calls=1 requests=['annotation:line/a2@7,annotation:rect/a1@7,annotations_collection:7@7,condition:10@7,page:20@7,page:21@7,takeoff:30@7,takeoff:31@7,takeoffs_collection:7@7'] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "delete_local mixed|denied": (
        "outcome=rejected message='The database rejected deletion.' commit=False tokens=() conflict=no authoritative=no created=() | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "delete_local mixed|conflict": (
        "outcome=conflict message='stale' commit=False tokens=() conflict=yes authoritative=no created=() | "
        "calls=0 requests=['annotation:line/a2@7,annotation:rect/a1@7,annotations_collection:7@7,condition:10@7,page:20@7,page:21@7,takeoff:30@7,takeoff:31@7,takeoffs_collection:7@7'] records=0 values=[None] verify=0 reloads=0 events=[]"
    ),
    "delete_local mixed|unknown": (
        "outcome=commit_status_unknown message='The database rejected deletion.' commit=True tokens=('lease-1',) conflict=no authoritative=no created=() | "
        "calls=2 requests=['annotation:line/a2@7,annotation:rect/a1@7,annotations_collection:7@7,condition:10@7,page:20@7,page:21@7,takeoff:30@7,takeoff:31@7,takeoffs_collection:7@7'] records=6 values=[None] verify=0 reloads=0 events=[]"
    ),
    "delete_local mixed|reload_failed": (
        "outcome=committed_projection_failed message='The deletion committed, but the local database projection could not be refreshed.' commit=True tokens=() conflict=no authoritative=yes created=() | "
        "calls=2 requests=['annotation:line/a2@7,annotation:rect/a1@7,annotations_collection:7@7,condition:10@7,page:20@7,page:21@7,takeoff:30@7,takeoff:31@7,takeoffs_collection:7@7'] records=6 values=[True] verify=0 reloads=1 events=[]"
    ),
    "delete_local mixed|other_database": (
        "outcome=committed message='' commit=True tokens=() conflict=no authoritative=yes created=() | "
        "calls=2 requests=['annotation:line/a2@7,annotation:rect/a1@7,annotations_collection:7@7,condition:10@7,page:20@7,page:21@7,takeoff:30@7,takeoff:31@7,takeoffs_collection:7@7'] records=6 values=[True] verify=0 reloads=1 events=['DatabaseRefreshedEvent']"
    ),
    "delete_local mixed|equivalent_path": (
        "outcome=committed message='' commit=True tokens=() conflict=no authoritative=yes created=() | "
        "calls=2 requests=['annotation:line/a2@7,annotation:rect/a1@7,annotations_collection:7@7,condition:10@7,page:20@7,page:21@7,takeoff:30@7,takeoff:31@7,takeoffs_collection:7@7'] records=6 values=[True] verify=0 reloads=1 events=['DatabaseRefreshedEvent']"
    ),
    "delete_local takeoffs only without refresh|failure": (
        "outcome=failed_before_commit message='The takeoff deletion was incomplete.' commit=False tokens=() conflict=no authoritative=no created=() | "
        "calls=1 requests=['page:20@7,takeoff:30@7,takeoffs_collection:7@7'] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "delete_local takeoffs only without refresh|denied": (
        "outcome=rejected message='The database rejected deletion.' commit=False tokens=() conflict=no authoritative=no created=() | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "delete_local takeoffs only without refresh|conflict": (
        "outcome=conflict message='stale' commit=False tokens=() conflict=yes authoritative=no created=() | "
        "calls=0 requests=['page:20@7,takeoff:30@7,takeoffs_collection:7@7'] records=0 values=[None] verify=0 reloads=0 events=[]"
    ),
    "delete_local takeoffs only without refresh|unknown": (
        "outcome=commit_status_unknown message='The database rejected deletion.' commit=True tokens=('lease-1',) conflict=no authoritative=no created=() | "
        "calls=1 requests=['page:20@7,takeoff:30@7,takeoffs_collection:7@7'] records=2 values=[None] verify=0 reloads=0 events=[]"
    ),
    "delete_local takeoffs only without refresh|reload_failed": (
        "outcome=committed message='' commit=True tokens=() conflict=no authoritative=yes created=() | "
        "calls=1 requests=['page:20@7,takeoff:30@7,takeoffs_collection:7@7'] records=2 values=[True] verify=0 reloads=0 events=[]"
    ),
    "delete_local takeoffs only without refresh|other_database": (
        "outcome=committed message='' commit=True tokens=() conflict=no authoritative=yes created=() | "
        "calls=1 requests=['page:20@7,takeoff:30@7,takeoffs_collection:7@7'] records=2 values=[True] verify=0 reloads=0 events=[]"
    ),
    "delete_local takeoffs only without refresh|equivalent_path": (
        "outcome=committed message='' commit=True tokens=() conflict=no authoritative=yes created=() | "
        "calls=1 requests=['page:20@7,takeoff:30@7,takeoffs_collection:7@7'] records=2 values=[True] verify=0 reloads=0 events=[]"
    ),
    "delete_local annotations only|failure": (
        "outcome=failed_before_commit message='The annotation deletion was incomplete.' commit=False tokens=() conflict=no authoritative=no created=() | "
        "calls=1 requests=['annotation:rect/a1@7,annotations_collection:7@7'] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "delete_local annotations only|denied": (
        "outcome=rejected message='The database rejected deletion.' commit=False tokens=() conflict=no authoritative=no created=() | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "delete_local annotations only|conflict": (
        "outcome=conflict message='stale' commit=False tokens=() conflict=yes authoritative=no created=() | "
        "calls=0 requests=['annotation:rect/a1@7,annotations_collection:7@7'] records=0 values=[None] verify=0 reloads=0 events=[]"
    ),
    "delete_local annotations only|unknown": (
        "outcome=commit_status_unknown message='The database rejected deletion.' commit=True tokens=('lease-1',) conflict=no authoritative=no created=() | "
        "calls=1 requests=['annotation:rect/a1@7,annotations_collection:7@7'] records=2 values=[None] verify=0 reloads=0 events=[]"
    ),
    "delete_local annotations only|reload_failed": (
        "outcome=committed_projection_failed message='The deletion committed, but the local database projection could not be refreshed.' commit=True tokens=() conflict=no authoritative=yes created=() | "
        "calls=1 requests=['annotation:rect/a1@7,annotations_collection:7@7'] records=2 values=[True] verify=0 reloads=1 events=[]"
    ),
    "delete_local annotations only|other_database": (
        "outcome=committed message='' commit=True tokens=() conflict=no authoritative=yes created=() | "
        "calls=1 requests=['annotation:rect/a1@7,annotations_collection:7@7'] records=2 values=[True] verify=0 reloads=1 events=['DatabaseRefreshedEvent']"
    ),
    "delete_local annotations only|equivalent_path": (
        "outcome=committed message='' commit=True tokens=() conflict=no authoritative=yes created=() | "
        "calls=1 requests=['annotation:rect/a1@7,annotations_collection:7@7'] records=2 values=[True] verify=0 reloads=1 events=['DatabaseRefreshedEvent']"
    ),
    "geometry_local mixed|failure": (
        "outcome=failed_before_commit message='The takeoff position update was incomplete.' commit=False tokens=() conflict=no authoritative=no created=() | "
        "calls=1 requests=['annotation:rect/a1@7,condition:10@7,page:20@7,page:21@7,takeoff:30@7,takeoff:31@7,takeoff:32@7'] records=0 values=[] verify=1 reloads=0 events=[]"
    ),
    "geometry_local mixed|denied": (
        "outcome=rejected message='The database rejected the geometry update.' commit=False tokens=() conflict=no authoritative=no created=() | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "geometry_local mixed|conflict": (
        "outcome=conflict message='stale' commit=False tokens=() conflict=yes authoritative=no created=() | "
        "calls=0 requests=['annotation:rect/a1@7,condition:10@7,page:20@7,page:21@7,takeoff:30@7,takeoff:31@7,takeoff:32@7'] records=0 values=[None] verify=0 reloads=0 events=[]"
    ),
    "geometry_local mixed|unknown": (
        "outcome=commit_status_unknown message='The database rejected the geometry update.' commit=True tokens=('lease-1',) conflict=no authoritative=no created=() | "
        "calls=3 requests=['annotation:rect/a1@7,condition:10@7,page:20@7,page:21@7,takeoff:30@7,takeoff:31@7,takeoff:32@7'] records=4 values=[None] verify=1 reloads=0 events=[]"
    ),
    "geometry_local mixed|reload_failed": (
        "outcome=committed_projection_failed message='The geometry update committed, but the local database projection could not be refreshed.' commit=True tokens=() conflict=no authoritative=yes created=() | "
        "calls=3 requests=['annotation:rect/a1@7,condition:10@7,page:20@7,page:21@7,takeoff:30@7,takeoff:31@7,takeoff:32@7'] records=4 values=[True] verify=1 reloads=1 events=[]"
    ),
    "geometry_local mixed|other_database": (
        "outcome=committed message='' commit=True tokens=() conflict=no authoritative=yes created=() | "
        "calls=3 requests=['annotation:rect/a1@7,condition:10@7,page:20@7,page:21@7,takeoff:30@7,takeoff:31@7,takeoff:32@7'] records=4 values=[True] verify=1 reloads=1 events=['DatabaseRefreshedEvent']"
    ),
    "geometry_local mixed|equivalent_path": (
        "outcome=committed message='' commit=True tokens=() conflict=no authoritative=yes created=() | "
        "calls=3 requests=['annotation:rect/a1@7,condition:10@7,page:20@7,page:21@7,takeoff:30@7,takeoff:31@7,takeoff:32@7'] records=4 values=[True] verify=1 reloads=1 events=['DatabaseRefreshedEvent']"
    ),
    "geometry_local rotation only|failure": (
        "outcome=failed_before_commit message='The takeoff rotation update was incomplete.' commit=False tokens=() conflict=no authoritative=no created=() | "
        "calls=1 requests=['page:21@7,takeoff:32@7'] records=0 values=[] verify=1 reloads=0 events=[]"
    ),
    "geometry_local rotation only|denied": (
        "outcome=rejected message='The database rejected the geometry update.' commit=False tokens=() conflict=no authoritative=no created=() | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "geometry_local rotation only|conflict": (
        "outcome=conflict message='stale' commit=False tokens=() conflict=yes authoritative=no created=() | "
        "calls=0 requests=['page:21@7,takeoff:32@7'] records=0 values=[None] verify=0 reloads=0 events=[]"
    ),
    "geometry_local rotation only|unknown": (
        "outcome=commit_status_unknown message='The database rejected the geometry update.' commit=True tokens=('lease-1',) conflict=no authoritative=no created=() | "
        "calls=1 requests=['page:21@7,takeoff:32@7'] records=1 values=[None] verify=1 reloads=0 events=[]"
    ),
    "geometry_local rotation only|reload_failed": (
        "outcome=committed_projection_failed message='The geometry update committed, but the local database projection could not be refreshed.' commit=True tokens=() conflict=no authoritative=yes created=() | "
        "calls=1 requests=['page:21@7,takeoff:32@7'] records=1 values=[True] verify=1 reloads=1 events=[]"
    ),
    "geometry_local rotation only|other_database": (
        "outcome=committed message='' commit=True tokens=() conflict=no authoritative=yes created=() | "
        "calls=1 requests=['page:21@7,takeoff:32@7'] records=1 values=[True] verify=1 reloads=1 events=['DatabaseRefreshedEvent']"
    ),
    "geometry_local rotation only|equivalent_path": (
        "outcome=committed message='' commit=True tokens=() conflict=no authoritative=yes created=() | "
        "calls=1 requests=['page:21@7,takeoff:32@7'] records=1 values=[True] verify=1 reloads=1 events=['DatabaseRefreshedEvent']"
    ),
    "geometry_local annotations only without refresh|failure": (
        "outcome=failed_before_commit message='The annotation position update was incomplete.' commit=False tokens=() conflict=no authoritative=no created=() | "
        "calls=1 requests=['annotation:line/a1@7'] records=0 values=[] verify=1 reloads=0 events=[]"
    ),
    "geometry_local annotations only without refresh|denied": (
        "outcome=rejected message='The database rejected the geometry update.' commit=False tokens=() conflict=no authoritative=no created=() | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "geometry_local annotations only without refresh|conflict": (
        "outcome=conflict message='stale' commit=False tokens=() conflict=yes authoritative=no created=() | "
        "calls=0 requests=['annotation:line/a1@7'] records=0 values=[None] verify=0 reloads=0 events=[]"
    ),
    "geometry_local annotations only without refresh|unknown": (
        "outcome=commit_status_unknown message='The database rejected the geometry update.' commit=True tokens=('lease-1',) conflict=no authoritative=no created=() | "
        "calls=1 requests=['annotation:line/a1@7'] records=1 values=[None] verify=1 reloads=0 events=[]"
    ),
    "geometry_local annotations only without refresh|reload_failed": (
        "outcome=committed message='' commit=True tokens=() conflict=no authoritative=yes created=() | "
        "calls=1 requests=['annotation:line/a1@7'] records=1 values=[True] verify=1 reloads=0 events=[]"
    ),
    "geometry_local annotations only without refresh|other_database": (
        "outcome=committed message='' commit=True tokens=() conflict=no authoritative=yes created=() | "
        "calls=1 requests=['annotation:line/a1@7'] records=1 values=[True] verify=1 reloads=0 events=[]"
    ),
    "geometry_local annotations only without refresh|equivalent_path": (
        "outcome=committed message='' commit=True tokens=() conflict=no authoritative=yes created=() | "
        "calls=1 requests=['annotation:line/a1@7'] records=1 values=[True] verify=1 reloads=0 events=[]"
    ),
    "properties_local takeoff_text|failure": (
        "outcome=failed_before_commit message='The plan property update was incomplete.' commit=False tokens=() conflict=no authoritative=no created=() | "
        "calls=1 requests=['page:20@7,takeoff:30@7,takeoff:31@7'] records=0 values=[] verify=1 reloads=0 events=[]"
    ),
    "properties_local takeoff_text|denied": (
        "outcome=rejected message='The database rejected the property update.' commit=False tokens=() conflict=no authoritative=no created=() | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "properties_local takeoff_text|conflict": (
        "outcome=conflict message='stale' commit=False tokens=() conflict=yes authoritative=no created=() | "
        "calls=0 requests=['page:20@7,takeoff:30@7,takeoff:31@7'] records=0 values=[None] verify=0 reloads=0 events=[]"
    ),
    "properties_local takeoff_text|unknown": (
        "outcome=commit_status_unknown message='The database rejected the property update.' commit=True tokens=('lease-1',) conflict=no authoritative=no created=() | "
        "calls=1 requests=['page:20@7,takeoff:30@7,takeoff:31@7'] records=1 values=[None] verify=1 reloads=0 events=[]"
    ),
    "properties_local takeoff_text|reload_failed": (
        "outcome=committed_projection_failed message='The property update committed, but the local database projection could not be refreshed.' commit=True tokens=() conflict=no authoritative=yes created=() | "
        "calls=1 requests=['page:20@7,takeoff:30@7,takeoff:31@7'] records=1 values=[True] verify=1 reloads=1 events=[]"
    ),
    "properties_local takeoff_text|other_database": (
        "outcome=failed_before_commit message='The property mutation no longer owns the current Bid.' commit=False tokens=() conflict=no authoritative=no created=() | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "properties_local takeoff_text|equivalent_path": (
        "outcome=committed message='' commit=True tokens=() conflict=no authoritative=yes created=() | "
        "calls=1 requests=['page:20@7,takeoff:30@7,takeoff:31@7'] records=1 values=[True] verify=1 reloads=1 events=['DatabaseRefreshedEvent']"
    ),
    "properties_local takeoff_area|failure": (
        "outcome=failed_before_commit message='The plan property update was incomplete.' commit=False tokens=() conflict=no authoritative=no created=() | "
        "calls=1 requests=['takeoff:30@7,takeoff:31@7,takeoff:32@7'] records=0 values=[] verify=1 reloads=0 events=[]"
    ),
    "properties_local takeoff_area|denied": (
        "outcome=rejected message='The database rejected the property update.' commit=False tokens=() conflict=no authoritative=no created=() | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "properties_local takeoff_area|conflict": (
        "outcome=conflict message='stale' commit=False tokens=() conflict=yes authoritative=no created=() | "
        "calls=0 requests=['takeoff:30@7,takeoff:31@7,takeoff:32@7'] records=0 values=[None] verify=0 reloads=0 events=[]"
    ),
    "properties_local takeoff_area|unknown": (
        "outcome=commit_status_unknown message='The database rejected the property update.' commit=True tokens=('lease-1',) conflict=no authoritative=no created=() | "
        "calls=2 requests=['takeoff:30@7,takeoff:31@7,takeoff:32@7'] records=3 values=[None] verify=1 reloads=0 events=[]"
    ),
    "properties_local takeoff_area|reload_failed": (
        "outcome=committed_projection_failed message='The property update committed, but the local database projection could not be refreshed.' commit=True tokens=() conflict=no authoritative=yes created=() | "
        "calls=2 requests=['takeoff:30@7,takeoff:31@7,takeoff:32@7'] records=3 values=[True] verify=1 reloads=1 events=[]"
    ),
    "properties_local takeoff_area|other_database": (
        "outcome=failed_before_commit message='The property mutation no longer owns the current Bid.' commit=False tokens=() conflict=no authoritative=no created=() | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "properties_local takeoff_area|equivalent_path": (
        "outcome=committed message='' commit=True tokens=() conflict=no authoritative=yes created=() | "
        "calls=2 requests=['takeoff:30@7,takeoff:31@7,takeoff:32@7'] records=3 values=[True] verify=1 reloads=1 events=['DatabaseRefreshedEvent']"
    ),
    "properties_local takeoff_condition|failure": (
        "outcome=failed_before_commit message='The plan property update was incomplete.' commit=False tokens=() conflict=no authoritative=no created=() | "
        "calls=1 requests=['takeoff:30@7,takeoff:31@7,takeoff:32@7'] records=0 values=[] verify=1 reloads=0 events=[]"
    ),
    "properties_local takeoff_condition|denied": (
        "outcome=rejected message='The database rejected the property update.' commit=False tokens=() conflict=no authoritative=no created=() | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "properties_local takeoff_condition|conflict": (
        "outcome=conflict message='stale' commit=False tokens=() conflict=yes authoritative=no created=() | "
        "calls=0 requests=['takeoff:30@7,takeoff:31@7,takeoff:32@7'] records=0 values=[None] verify=0 reloads=0 events=[]"
    ),
    "properties_local takeoff_condition|unknown": (
        "outcome=commit_status_unknown message='The database rejected the property update.' commit=True tokens=('lease-1',) conflict=no authoritative=no created=() | "
        "calls=1 requests=['takeoff:30@7,takeoff:31@7,takeoff:32@7'] records=2 values=[None] verify=1 reloads=0 events=[]"
    ),
    "properties_local takeoff_condition|reload_failed": (
        "outcome=committed_projection_failed message='The property update committed, but the local database projection could not be refreshed.' commit=True tokens=() conflict=no authoritative=yes created=() | "
        "calls=1 requests=['takeoff:30@7,takeoff:31@7,takeoff:32@7'] records=2 values=[True] verify=1 reloads=1 events=[]"
    ),
    "properties_local takeoff_condition|other_database": (
        "outcome=failed_before_commit message='The property mutation no longer owns the current Bid.' commit=False tokens=() conflict=no authoritative=no created=() | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "properties_local takeoff_condition|equivalent_path": (
        "outcome=committed message='' commit=True tokens=() conflict=no authoritative=yes created=() | "
        "calls=1 requests=['takeoff:30@7,takeoff:31@7,takeoff:32@7'] records=2 values=[True] verify=1 reloads=1 events=['DatabaseRefreshedEvent']"
    ),
    "properties_local takeoff_negative|failure": (
        "outcome=failed_before_commit message='The plan property update was incomplete.' commit=False tokens=() conflict=no authoritative=no created=() | "
        "calls=1 requests=['takeoff:30@7,takeoff:31@7,takeoff:32@7'] records=0 values=[] verify=1 reloads=0 events=[]"
    ),
    "properties_local takeoff_negative|denied": (
        "outcome=rejected message='The database rejected the property update.' commit=False tokens=() conflict=no authoritative=no created=() | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "properties_local takeoff_negative|conflict": (
        "outcome=conflict message='stale' commit=False tokens=() conflict=yes authoritative=no created=() | "
        "calls=0 requests=['takeoff:30@7,takeoff:31@7,takeoff:32@7'] records=0 values=[None] verify=0 reloads=0 events=[]"
    ),
    "properties_local takeoff_negative|unknown": (
        "outcome=commit_status_unknown message='The database rejected the property update.' commit=True tokens=('lease-1',) conflict=no authoritative=no created=() | "
        "calls=2 requests=['takeoff:30@7,takeoff:31@7,takeoff:32@7'] records=3 values=[None] verify=1 reloads=0 events=[]"
    ),
    "properties_local takeoff_negative|reload_failed": (
        "outcome=committed_projection_failed message='The property update committed, but the local database projection could not be refreshed.' commit=True tokens=() conflict=no authoritative=yes created=() | "
        "calls=2 requests=['takeoff:30@7,takeoff:31@7,takeoff:32@7'] records=3 values=[True] verify=1 reloads=1 events=[]"
    ),
    "properties_local takeoff_negative|other_database": (
        "outcome=failed_before_commit message='The property mutation no longer owns the current Bid.' commit=False tokens=() conflict=no authoritative=no created=() | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "properties_local takeoff_negative|equivalent_path": (
        "outcome=committed message='' commit=True tokens=() conflict=no authoritative=yes created=() | "
        "calls=2 requests=['takeoff:30@7,takeoff:31@7,takeoff:32@7'] records=3 values=[True] verify=1 reloads=1 events=['DatabaseRefreshedEvent']"
    ),
    "properties_local takeoff_curve|failure": (
        "outcome=failed_before_commit message='The plan property update was incomplete.' commit=False tokens=() conflict=no authoritative=no created=() | "
        "calls=1 requests=['takeoff:30@7,takeoff:31@7'] records=0 values=[] verify=1 reloads=0 events=[]"
    ),
    "properties_local takeoff_curve|denied": (
        "outcome=rejected message='The database rejected the property update.' commit=False tokens=() conflict=no authoritative=no created=() | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "properties_local takeoff_curve|conflict": (
        "outcome=conflict message='stale' commit=False tokens=() conflict=yes authoritative=no created=() | "
        "calls=0 requests=['takeoff:30@7,takeoff:31@7'] records=0 values=[None] verify=0 reloads=0 events=[]"
    ),
    "properties_local takeoff_curve|unknown": (
        "outcome=commit_status_unknown message='The database rejected the property update.' commit=True tokens=('lease-1',) conflict=no authoritative=no created=() | "
        "calls=1 requests=['takeoff:30@7,takeoff:31@7'] records=1 values=[None] verify=1 reloads=0 events=[]"
    ),
    "properties_local takeoff_curve|reload_failed": (
        "outcome=committed_projection_failed message='The property update committed, but the local database projection could not be refreshed.' commit=True tokens=() conflict=no authoritative=yes created=() | "
        "calls=1 requests=['takeoff:30@7,takeoff:31@7'] records=1 values=[True] verify=1 reloads=1 events=[]"
    ),
    "properties_local takeoff_curve|other_database": (
        "outcome=failed_before_commit message='The property mutation no longer owns the current Bid.' commit=False tokens=() conflict=no authoritative=no created=() | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "properties_local takeoff_curve|equivalent_path": (
        "outcome=committed message='' commit=True tokens=() conflict=no authoritative=yes created=() | "
        "calls=1 requests=['takeoff:30@7,takeoff:31@7'] records=1 values=[True] verify=1 reloads=1 events=['DatabaseRefreshedEvent']"
    ),
    "properties_local annotation_text|failure": (
        "outcome=failed_before_commit message='The plan property update was incomplete.' commit=False tokens=() conflict=no authoritative=no created=() | "
        "calls=1 requests=['annotation:rect/a1@7'] records=0 values=[] verify=1 reloads=0 events=[]"
    ),
    "properties_local annotation_text|denied": (
        "outcome=rejected message='The database rejected the property update.' commit=False tokens=() conflict=no authoritative=no created=() | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "properties_local annotation_text|conflict": (
        "outcome=conflict message='stale' commit=False tokens=() conflict=yes authoritative=no created=() | "
        "calls=0 requests=['annotation:rect/a1@7'] records=0 values=[None] verify=0 reloads=0 events=[]"
    ),
    "properties_local annotation_text|unknown": (
        "outcome=commit_status_unknown message='The database rejected the property update.' commit=True tokens=('lease-1',) conflict=no authoritative=no created=() | "
        "calls=1 requests=['annotation:rect/a1@7'] records=1 values=[None] verify=1 reloads=0 events=[]"
    ),
    "properties_local annotation_text|reload_failed": (
        "outcome=committed_projection_failed message='The property update committed, but the local database projection could not be refreshed.' commit=True tokens=() conflict=no authoritative=yes created=() | "
        "calls=1 requests=['annotation:rect/a1@7'] records=1 values=[True] verify=1 reloads=1 events=[]"
    ),
    "properties_local annotation_text|other_database": (
        "outcome=committed message='' commit=True tokens=() conflict=no authoritative=yes created=() | "
        "calls=1 requests=['annotation:rect/a1@7'] records=1 values=[True] verify=1 reloads=1 events=['DatabaseRefreshedEvent']"
    ),
    "properties_local annotation_text|equivalent_path": (
        "outcome=committed message='' commit=True tokens=() conflict=no authoritative=yes created=() | "
        "calls=1 requests=['annotation:rect/a1@7'] records=1 values=[True] verify=1 reloads=1 events=['DatabaseRefreshedEvent']"
    ),
    "properties_local annotation_style without refresh|failure": (
        "outcome=failed_before_commit message='The plan property update was incomplete.' commit=False tokens=() conflict=no authoritative=no created=() | "
        "calls=1 requests=['annotation:rect/a1@7'] records=0 values=[] verify=1 reloads=0 events=[]"
    ),
    "properties_local annotation_style without refresh|denied": (
        "outcome=rejected message='The database rejected the property update.' commit=False tokens=() conflict=no authoritative=no created=() | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "properties_local annotation_style without refresh|conflict": (
        "outcome=conflict message='stale' commit=False tokens=() conflict=yes authoritative=no created=() | "
        "calls=0 requests=['annotation:rect/a1@7'] records=0 values=[None] verify=0 reloads=0 events=[]"
    ),
    "properties_local annotation_style without refresh|unknown": (
        "outcome=commit_status_unknown message='The database rejected the property update.' commit=True tokens=('lease-1',) conflict=no authoritative=no created=() | "
        "calls=1 requests=['annotation:rect/a1@7'] records=1 values=[None] verify=1 reloads=0 events=[]"
    ),
    "properties_local annotation_style without refresh|reload_failed": (
        "outcome=committed message='' commit=True tokens=() conflict=no authoritative=yes created=() | "
        "calls=1 requests=['annotation:rect/a1@7'] records=1 values=[True] verify=1 reloads=0 events=[]"
    ),
    "properties_local annotation_style without refresh|other_database": (
        "outcome=committed message='' commit=True tokens=() conflict=no authoritative=yes created=() | "
        "calls=1 requests=['annotation:rect/a1@7'] records=1 values=[True] verify=1 reloads=0 events=[]"
    ),
    "properties_local annotation_style without refresh|equivalent_path": (
        "outcome=committed message='' commit=True tokens=() conflict=no authoritative=yes created=() | "
        "calls=1 requests=['annotation:rect/a1@7'] records=1 values=[True] verify=1 reloads=0 events=[]"
    ),
    "paste_local same bid|failure": (
        "outcome=failed_before_commit message='The paste returned an incomplete Takeoff UID map.' commit=False tokens=() conflict=no authoritative=no created=() | "
        "calls=1 requests=['annotations_collection:7@7,condition:c1@7,page:p1@7,takeoffs_collection:7@7'] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "paste_local same bid|denied": (
        "outcome=rejected message='The database rejected paste.' commit=False tokens=() conflict=no authoritative=no created=() | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "paste_local same bid|conflict": (
        "outcome=conflict message='stale' commit=False tokens=() conflict=yes authoritative=no created=() | "
        "calls=0 requests=['annotations_collection:7@7,condition:c1@7,page:p1@7,takeoffs_collection:7@7'] records=0 values=[None] verify=0 reloads=0 events=[]"
    ),
    "paste_local same bid|unknown": (
        "outcome=commit_status_unknown message='The database rejected paste.' commit=True tokens=('lease-1',) conflict=no authoritative=no created=() | "
        "calls=4 requests=['annotations_collection:7@7,condition:c1@7,page:p1@7,takeoffs_collection:7@7'] records=6 values=[None] verify=0 reloads=0 events=[]"
    ),
    "paste_local same bid|reload_failed": (
        "outcome=committed_projection_failed message='The paste committed, but the local database projection could not be refreshed.' commit=True tokens=() conflict=no authoritative=yes created=('p-new', 'h-new', 'named-new', 'rect-new') | "
        "calls=4 requests=['annotations_collection:7@7,condition:c1@7,page:p1@7,takeoffs_collection:7@7'] records=6 values=[{'takeoff_uids': {'parent': 'p-new', 'hole': 'h-new'}, 'annotation_uids': {'namedview/shared': 'named-new', 'rect/shared': 'rect-new'}, 'condition_uids': {}}] verify=0 reloads=1 events=[]"
    ),
    "paste_local same bid|other_database": (
        "outcome=committed message='' commit=True tokens=() conflict=no authoritative=yes created=('p-new', 'h-new', 'named-new', 'rect-new') | "
        "calls=4 requests=['annotations_collection:7@7,condition:c1@7,page:p1@7,takeoffs_collection:7@7'] records=6 values=[{'takeoff_uids': {'parent': 'p-new', 'hole': 'h-new'}, 'annotation_uids': {'namedview/shared': 'named-new', 'rect/shared': 'rect-new'}, 'condition_uids': {}}] verify=0 reloads=1 events=['DatabaseRefreshedEvent']"
    ),
    "paste_local same bid|equivalent_path": (
        "outcome=committed message='' commit=True tokens=() conflict=no authoritative=yes created=('p-new', 'h-new', 'named-new', 'rect-new') | "
        "calls=4 requests=['annotations_collection:7@7,condition:c1@7,page:p1@7,takeoffs_collection:7@7'] records=6 values=[{'takeoff_uids': {'parent': 'p-new', 'hole': 'h-new'}, 'annotation_uids': {'namedview/shared': 'named-new', 'rect/shared': 'rect-new'}, 'condition_uids': {}}] verify=0 reloads=1 events=['DatabaseRefreshedEvent']"
    ),
    "paste_local cross bid|failure": (
        "outcome=failed_before_commit message='The paste did not create every required condition.' commit=False tokens=() conflict=no authoritative=no created=() | "
        "calls=1 requests=['annotations_collection:7@7,conditions_collection:7@7,page:p1@7,takeoffs_collection:7@7'] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "paste_local cross bid|denied": (
        "outcome=rejected message='The database rejected paste.' commit=False tokens=() conflict=no authoritative=no created=() | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "paste_local cross bid|conflict": (
        "outcome=conflict message='stale' commit=False tokens=() conflict=yes authoritative=no created=() | "
        "calls=0 requests=['annotations_collection:7@7,conditions_collection:7@7,page:p1@7,takeoffs_collection:7@7'] records=0 values=[None] verify=0 reloads=0 events=[]"
    ),
    "paste_local cross bid|unknown": (
        "outcome=commit_status_unknown message='The database rejected paste.' commit=True tokens=('lease-1',) conflict=no authoritative=no created=() | "
        "calls=5 requests=['annotations_collection:7@7,conditions_collection:7@7,page:p1@7,takeoffs_collection:7@7'] records=8 values=[None] verify=0 reloads=0 events=[]"
    ),
    "paste_local cross bid|reload_failed": (
        "outcome=committed_projection_failed message='The paste committed, but the local database projection could not be refreshed.' commit=True tokens=() conflict=no authoritative=yes created=('p-new', 'h-new', 'named-new', 'rect-new') | "
        "calls=5 requests=['annotations_collection:7@7,conditions_collection:7@7,page:p1@7,takeoffs_collection:7@7'] records=8 values=[{'takeoff_uids': {'parent': 'p-new', 'hole': 'h-new'}, 'annotation_uids': {'namedview/shared': 'named-new', 'rect/shared': 'rect-new'}, 'condition_uids': {'c1': 'c9'}}] verify=0 reloads=1 events=[]"
    ),
    "paste_local cross bid|other_database": (
        "outcome=committed message='' commit=True tokens=() conflict=no authoritative=yes created=('p-new', 'h-new', 'named-new', 'rect-new') | "
        "calls=5 requests=['annotations_collection:7@7,conditions_collection:7@7,page:p1@7,takeoffs_collection:7@7'] records=8 values=[{'takeoff_uids': {'parent': 'p-new', 'hole': 'h-new'}, 'annotation_uids': {'namedview/shared': 'named-new', 'rect/shared': 'rect-new'}, 'condition_uids': {'c1': 'c9'}}] verify=0 reloads=1 events=['DatabaseRefreshedEvent']"
    ),
    "paste_local cross bid|equivalent_path": (
        "outcome=committed message='' commit=True tokens=() conflict=no authoritative=yes created=('p-new', 'h-new', 'named-new', 'rect-new') | "
        "calls=5 requests=['annotations_collection:7@7,conditions_collection:7@7,page:p1@7,takeoffs_collection:7@7'] records=8 values=[{'takeoff_uids': {'parent': 'p-new', 'hole': 'h-new'}, 'annotation_uids': {'namedview/shared': 'named-new', 'rect/shared': 'rect-new'}, 'condition_uids': {'c1': 'c9'}}] verify=0 reloads=1 events=['DatabaseRefreshedEvent']"
    ),
}
_QUEUE_SCENARIO_EXPECTED = {
    "queue_project_create|denied": (
        "outcome=rejected message='The database rejected the project update.' commit=False tokens=() conflict=no authoritative=no created=() | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "queue_project_create|conflict": (
        "outcome=conflict message='stale' commit=False tokens=() conflict=yes authoritative=no created=() | "
        "calls=0 requests=['projects_collection:database@None'] records=0 values=[None] verify=0 reloads=0 events=[]"
    ),
    "queue_project_create|unknown": (
        "outcome=commit_status_unknown message='The database rejected the project update.' commit=True tokens=('lease-1',) conflict=no authoritative=no created=() | "
        "calls=1 requests=['projects_collection:database@None'] records=2 values=[None] verify=0 reloads=0 events=[]"
    ),
    "queue_bid_create|denied": (
        "outcome=rejected message='The database rejected the project update.' commit=False tokens=() conflict=no authoritative=no created=() | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "queue_bid_create|conflict": (
        "outcome=conflict message='stale' commit=False tokens=() conflict=yes authoritative=no created=() | "
        "calls=0 requests=['default_layers_collection:database@None,employee:5@None,job_status:2@None,project:3@None,project_bids:3@None'] records=0 values=[None] verify=0 reloads=0 events=[]"
    ),
    "queue_bid_create|unknown": (
        "outcome=commit_status_unknown message='The database rejected the project update.' commit=True tokens=('lease-1',) conflict=no authoritative=no created=() | "
        "calls=1 requests=['default_layers_collection:database@None,employee:5@None,job_status:2@None,project:3@None,project_bids:3@None'] records=2 values=[None] verify=0 reloads=0 events=[]"
    ),
    "queue_bid_create orphan|denied": (
        "outcome=rejected message='The database rejected the project update.' commit=False tokens=() conflict=no authoritative=no created=() | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "queue_bid_create orphan|conflict": (
        "outcome=conflict message='stale' commit=False tokens=() conflict=yes authoritative=no created=() | "
        "calls=0 requests=['default_layers_collection:database@None,project_bids:orphan@None'] records=0 values=[None] verify=0 reloads=0 events=[]"
    ),
    "queue_bid_create orphan|unknown": (
        "outcome=commit_status_unknown message='The database rejected the project update.' commit=True tokens=('lease-1',) conflict=no authoritative=no created=() | "
        "calls=1 requests=['default_layers_collection:database@None,project_bids:orphan@None'] records=2 values=[None] verify=0 reloads=0 events=[]"
    ),
    "queue_project_rename|denied": (
        "outcome=rejected message='The database rejected the project update.' commit=False tokens=() conflict=no authoritative=no created=() | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "queue_project_rename|conflict": (
        "outcome=conflict message='stale' commit=False tokens=() conflict=yes authoritative=no created=() | "
        "calls=0 requests=['project:3@None'] records=0 values=[None] verify=0 reloads=0 events=[]"
    ),
    "queue_project_rename|unknown": (
        "outcome=commit_status_unknown message='The database rejected the project update.' commit=True tokens=('lease-1',) conflict=no authoritative=no created=() | "
        "calls=1 requests=['project:3@None'] records=1 values=[None] verify=0 reloads=0 events=[]"
    ),
    "queue_bids_move|denied": (
        "outcome=rejected message='The database rejected the project update.' commit=False tokens=() conflict=no authoritative=no created=() | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "queue_bids_move|conflict": (
        "outcome=conflict message='stale' commit=False tokens=() conflict=yes authoritative=no created=() | "
        "calls=0 requests=['bid:7@7,bid:8@8,project_bids:3@None,project_bids:4@None'] records=0 values=[None] verify=0 reloads=0 events=[]"
    ),
    "queue_bids_move|unknown": (
        "outcome=commit_status_unknown message='The database rejected the project update.' commit=True tokens=('lease-1',) conflict=no authoritative=no created=() | "
        "calls=1 requests=['bid:7@7,bid:8@8,project_bids:3@None,project_bids:4@None'] records=4 values=[None] verify=0 reloads=0 events=[]"
    ),
    "queue_bids_move to orphan|denied": (
        "outcome=rejected message='The database rejected the project update.' commit=False tokens=() conflict=no authoritative=no created=() | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "queue_bids_move to orphan|conflict": (
        "outcome=conflict message='stale' commit=False tokens=() conflict=yes authoritative=no created=() | "
        "calls=0 requests=['bid:7@7,project_bids:orphan@None'] records=0 values=[None] verify=0 reloads=0 events=[]"
    ),
    "queue_bids_move to orphan|unknown": (
        "outcome=commit_status_unknown message='The database rejected the project update.' commit=True tokens=('lease-1',) conflict=no authoritative=no created=() | "
        "calls=1 requests=['bid:7@7,project_bids:orphan@None'] records=2 values=[None] verify=0 reloads=0 events=[]"
    ),
    "queue_bids_duplicate|denied": (
        "outcome=rejected message='The database rejected the project update.' commit=False tokens=() conflict=no authoritative=no created=() | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "queue_bids_duplicate|conflict": (
        "outcome=conflict message='stale' commit=False tokens=() conflict=yes authoritative=no created=() | "
        "calls=0 requests=['bid:7@7,bid:8@8,project_bids:4@None'] records=0 values=[None] verify=0 reloads=0 events=[]"
    ),
    "queue_bids_duplicate|unknown": (
        "outcome=commit_status_unknown message='The database rejected the project update.' commit=True tokens=('lease-1',) conflict=no authoritative=no created=() | "
        "calls=3 requests=['bid:7@7,bid:8@8,project_bids:4@None'] records=3 values=[None] verify=0 reloads=0 events=[]"
    ),
    "queue_bids_delete|denied": (
        "outcome=rejected message='The database rejected the project update.' commit=False tokens=() conflict=no authoritative=no created=() | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "queue_bids_delete|conflict": (
        "outcome=conflict message='stale' commit=False tokens=() conflict=yes authoritative=no created=() | "
        "calls=0 requests=['bid:7@7,bid:8@8,projects_collection:database@None'] records=0 values=[None] verify=0 reloads=0 events=[]"
    ),
    "queue_bids_delete|unknown": (
        "outcome=commit_status_unknown message='The database rejected the project update.' commit=True tokens=('lease-1',) conflict=no authoritative=no created=() | "
        "calls=1 requests=['bid:7@7,bid:8@8,projects_collection:database@None'] records=3 values=[None] verify=0 reloads=0 events=[]"
    ),
    "queue_projects_delete|denied": (
        "outcome=rejected message='The database rejected the project update.' commit=False tokens=() conflict=no authoritative=no created=() | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "queue_projects_delete|conflict": (
        "outcome=conflict message='stale' commit=False tokens=() conflict=yes authoritative=no created=() | "
        "calls=0 requests=['bid:31@31,bid:41@41,project:3@None,project:4@None,projects_collection:database@None'] records=0 values=[None] verify=0 reloads=0 events=[]"
    ),
    "queue_projects_delete|unknown": (
        "outcome=commit_status_unknown message='The database rejected the project update.' commit=True tokens=('lease-1',) conflict=no authoritative=no created=() | "
        "calls=1 requests=['bid:31@31,bid:41@41,project:3@None,project:4@None,projects_collection:database@None'] records=5 values=[None] verify=0 reloads=0 events=[]"
    ),
    "queue_bid_job_status_update|denied": (
        "outcome=rejected message='The database rejected the project update.' commit=False tokens=() conflict=no authoritative=no created=() | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "queue_bid_job_status_update|conflict": (
        "outcome=conflict message='stale' commit=False tokens=() conflict=yes authoritative=no created=() | "
        "calls=0 requests=['bid:7@7'] records=0 values=[None] verify=0 reloads=0 events=[]"
    ),
    "queue_bid_job_status_update|unknown": (
        "outcome=commit_status_unknown message='The database rejected the project update.' commit=True tokens=('lease-1',) conflict=no authoritative=no created=() | "
        "calls=1 requests=['bid:7@7'] records=1 values=[None] verify=0 reloads=0 events=[]"
    ),
    "queue_bid_areas_save|denied": (
        "outcome=rejected message='The database rejected the project update.' commit=False tokens=() conflict=no authoritative=no created=() | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "queue_bid_areas_save|conflict": (
        "outcome=conflict message='stale' commit=False tokens=() conflict=yes authoritative=no created=() | "
        "calls=0 requests=['area:5@7,area:6@7,areas_collection:7@7'] records=0 values=[None] verify=0 reloads=0 events=[]"
    ),
    "queue_bid_areas_save|unknown": (
        "outcome=commit_status_unknown message='The database rejected the project update.' commit=True tokens=('lease-1',) conflict=no authoritative=no created=() | "
        "calls=1 requests=['area:5@7,area:6@7,areas_collection:7@7'] records=4 values=[None] verify=0 reloads=0 events=[]"
    ),
    "queue_cover_sheet_save|denied": (
        "outcome=rejected message='The database rejected the project update.' commit=False tokens=() conflict=no authoritative=no created=() | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "queue_cover_sheet_save|conflict": (
        "outcome=conflict message='stale' commit=False tokens=() conflict=yes authoritative=no created=() | "
        "calls=0 requests=['annotations_collection:7@7,bid:7@7,conditions_collection:7@7,cover_sheet:7@7,employee:5@None,job_status:2@None,pages_collection:7@7,takeoffs_collection:7@7'] records=0 values=[None] verify=0 reloads=0 events=[]"
    ),
    "queue_cover_sheet_save|unknown": (
        "outcome=commit_status_unknown message='The database rejected the project update.' commit=True tokens=('lease-1',) conflict=no authoritative=no created=() | "
        "calls=1 requests=['annotations_collection:7@7,bid:7@7,conditions_collection:7@7,cover_sheet:7@7,employee:5@None,job_status:2@None,pages_collection:7@7,takeoffs_collection:7@7'] records=6 values=[None] verify=0 reloads=0 events=[]"
    ),
    "queue_condition_types_save|denied": (
        "outcome=rejected message='The database rejected the project update.' commit=False tokens=() conflict=no authoritative=no created=() | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "queue_condition_types_save|conflict": (
        "outcome=conflict message='stale' commit=False tokens=() conflict=yes authoritative=no created=() | "
        "calls=0 requests=['condition_type:8@None,condition_type:9@None,condition_types_collection:database@None'] records=0 values=[None] verify=0 reloads=0 events=[]"
    ),
    "queue_condition_types_save|unknown": (
        "outcome=commit_status_unknown message='The database rejected the project update.' commit=True tokens=('lease-1',) conflict=no authoritative=no created=() | "
        "calls=1 requests=['condition_type:8@None,condition_type:9@None,condition_types_collection:database@None'] records=4 values=[None] verify=0 reloads=0 events=[]"
    ),
    "queue_default_layer_insert|denied": (
        "outcome=rejected message='The database rejected the project update.' commit=False tokens=() conflict=no authoritative=no created=() | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "queue_default_layer_insert|conflict": (
        "outcome=conflict message='stale' commit=False tokens=() conflict=yes authoritative=no created=() | "
        "calls=0 requests=['default_layers_collection:database@None'] records=0 values=[None] verify=0 reloads=0 events=[]"
    ),
    "queue_default_layer_insert|unknown": (
        "outcome=commit_status_unknown message='The database rejected the project update.' commit=True tokens=('lease-1',) conflict=no authoritative=no created=() | "
        "calls=1 requests=['default_layers_collection:database@None'] records=1 values=[None] verify=0 reloads=0 events=[]"
    ),
    "queue_default_layers_delete|denied": (
        "outcome=rejected message='The database rejected the project update.' commit=False tokens=() conflict=no authoritative=no created=() | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "queue_default_layers_delete|conflict": (
        "outcome=conflict message='stale' commit=False tokens=() conflict=yes authoritative=no created=() | "
        "calls=0 requests=['default_layers_collection:database@None'] records=0 values=[None] verify=0 reloads=0 events=[]"
    ),
    "queue_default_layers_delete|unknown": (
        "outcome=commit_status_unknown message='The database rejected the project update.' commit=True tokens=('lease-1',) conflict=no authoritative=no created=() | "
        "calls=2 requests=['default_layers_collection:database@None'] records=1 values=[None] verify=0 reloads=0 events=[]"
    ),
    "queue_default_layer_update rename|denied": (
        "outcome=rejected message='The database rejected the project update.' commit=False tokens=() conflict=no authoritative=no created=() | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "queue_default_layer_update rename|conflict": (
        "outcome=conflict message='stale' commit=False tokens=() conflict=yes authoritative=no created=() | "
        "calls=0 requests=['default_layers_collection:database@None'] records=0 values=[None] verify=0 reloads=0 events=[]"
    ),
    "queue_default_layer_update rename|unknown": (
        "outcome=commit_status_unknown message='The database rejected the project update.' commit=True tokens=('lease-1',) conflict=no authoritative=no created=() | "
        "calls=1 requests=['default_layers_collection:database@None'] records=1 values=[None] verify=0 reloads=0 events=[]"
    ),
    "queue_default_layer_update show|denied": (
        "outcome=rejected message='The database rejected the project update.' commit=False tokens=() conflict=no authoritative=no created=() | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "queue_default_layer_update show|conflict": (
        "outcome=conflict message='stale' commit=False tokens=() conflict=yes authoritative=no created=() | "
        "calls=0 requests=['default_layers_collection:database@None'] records=0 values=[None] verify=0 reloads=0 events=[]"
    ),
    "queue_default_layer_update show|unknown": (
        "outcome=commit_status_unknown message='The database rejected the project update.' commit=True tokens=('lease-1',) conflict=no authoritative=no created=() | "
        "calls=1 requests=['default_layers_collection:database@None'] records=1 values=[None] verify=0 reloads=0 events=[]"
    ),
    "queue_default_layer_update show_all|denied": (
        "outcome=rejected message='The database rejected the project update.' commit=False tokens=() conflict=no authoritative=no created=() | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "queue_default_layer_update show_all|conflict": (
        "outcome=conflict message='stale' commit=False tokens=() conflict=yes authoritative=no created=() | "
        "calls=0 requests=['default_layers_collection:database@None'] records=0 values=[None] verify=0 reloads=0 events=[]"
    ),
    "queue_default_layer_update show_all|unknown": (
        "outcome=commit_status_unknown message='The database rejected the project update.' commit=True tokens=('lease-1',) conflict=no authoritative=no created=() | "
        "calls=1 requests=['default_layers_collection:database@None'] records=1 values=[None] verify=0 reloads=0 events=[]"
    ),
    "queue_default_layer_update reorder|denied": (
        "outcome=rejected message='The database rejected the project update.' commit=False tokens=() conflict=no authoritative=no created=() | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "queue_default_layer_update reorder|conflict": (
        "outcome=conflict message='stale' commit=False tokens=() conflict=yes authoritative=no created=() | "
        "calls=0 requests=['default_layers_collection:database@None'] records=0 values=[None] verify=0 reloads=0 events=[]"
    ),
    "queue_default_layer_update reorder|unknown": (
        "outcome=commit_status_unknown message='The database rejected the project update.' commit=True tokens=('lease-1',) conflict=no authoritative=no created=() | "
        "calls=1 requests=['default_layers_collection:database@None'] records=1 values=[None] verify=0 reloads=0 events=[]"
    ),
    "queue_job_statuses_save|denied": (
        "outcome=rejected message='The database rejected the project update.' commit=False tokens=() conflict=no authoritative=no created=() | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "queue_job_statuses_save|conflict": (
        "outcome=conflict message='stale' commit=False tokens=() conflict=yes authoritative=no created=() | "
        "calls=0 requests=['job_status:3@None,job_status:4@None,job_statuses_collection:database@None,projects_collection:database@None'] records=0 values=[None] verify=0 reloads=0 events=[]"
    ),
    "queue_job_statuses_save|unknown": (
        "outcome=commit_status_unknown message='The database rejected the project update.' commit=True tokens=('lease-1',) conflict=no authoritative=no created=() | "
        "calls=1 requests=['job_status:3@None,job_status:4@None,job_statuses_collection:database@None,projects_collection:database@None'] records=5 values=[None] verify=0 reloads=0 events=[]"
    ),
    "queue_employees_save|denied": (
        "outcome=rejected message='The database rejected the project update.' commit=False tokens=() conflict=no authoritative=no created=() | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "queue_employees_save|conflict": (
        "outcome=conflict message='stale' commit=False tokens=() conflict=yes authoritative=no created=() | "
        "calls=0 requests=['employees_collection:database@None,projects_collection:database@None'] records=0 values=[None] verify=0 reloads=0 events=[]"
    ),
    "queue_employees_save|unknown": (
        "outcome=commit_status_unknown message='The database rejected the project update.' commit=True tokens=('lease-1',) conflict=no authoritative=no created=() | "
        "calls=1 requests=['employees_collection:database@None,projects_collection:database@None'] records=3 values=[None] verify=0 reloads=0 events=[]"
    ),
    "queue_pay_classes_save|denied": (
        "outcome=rejected message='The database rejected the project update.' commit=False tokens=() conflict=no authoritative=no created=() | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "queue_pay_classes_save|conflict": (
        "outcome=conflict message='stale' commit=False tokens=() conflict=yes authoritative=no created=() | "
        "calls=0 requests=['employees_collection:database@None,pay_classes_collection:database@None'] records=0 values=[None] verify=0 reloads=0 events=[]"
    ),
    "queue_pay_classes_save|unknown": (
        "outcome=commit_status_unknown message='The database rejected the project update.' commit=True tokens=('lease-1',) conflict=no authoritative=no created=() | "
        "calls=1 requests=['employees_collection:database@None,pay_classes_collection:database@None'] records=3 values=[None] verify=0 reloads=0 events=[]"
    ),
    "queue_pages_delete|denied": (
        "outcome=rejected message='The database rejected the project update.' commit=False tokens=() conflict=no authoritative=no created=() | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "queue_pages_delete|conflict": (
        "outcome=conflict message='stale' commit=False tokens=() conflict=yes authoritative=no created=() | "
        "calls=0 requests=['annotation:rect/20-a@7,annotation:rect/21-a@7,annotations_collection:7@7,page:20@7,page:21@7,pages_collection:7@7,takeoff:20-t@7,takeoff:21-t@7,takeoffs_collection:7@7'] records=0 values=[None] verify=0 reloads=0 events=[]"
    ),
    "queue_pages_delete|unknown": (
        "outcome=commit_status_unknown message='The database rejected the project update.' commit=True tokens=('lease-1',) conflict=no authoritative=no created=() | "
        "calls=1 requests=['annotation:rect/20-a@7,annotation:rect/21-a@7,annotations_collection:7@7,page:20@7,page:21@7,pages_collection:7@7,takeoff:20-t@7,takeoff:21-t@7,takeoffs_collection:7@7'] records=9 values=[None] verify=0 reloads=0 events=[]"
    ),
    "queue_pages_delete single|denied": (
        "outcome=rejected message='The database rejected the project update.' commit=False tokens=() conflict=no authoritative=no created=() | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "queue_pages_delete single|conflict": (
        "outcome=conflict message='stale' commit=False tokens=() conflict=yes authoritative=no created=() | "
        "calls=0 requests=['annotation:rect/20-a@7,annotations_collection:7@7,page:20@7,pages_collection:7@7,takeoff:20-t@7,takeoffs_collection:7@7'] records=0 values=[None] verify=0 reloads=0 events=[]"
    ),
    "queue_pages_delete single|unknown": (
        "outcome=commit_status_unknown message='The database rejected the project update.' commit=True tokens=('lease-1',) conflict=no authoritative=no created=() | "
        "calls=1 requests=['annotation:rect/20-a@7,annotations_collection:7@7,page:20@7,pages_collection:7@7,takeoff:20-t@7,takeoffs_collection:7@7'] records=6 values=[None] verify=0 reloads=0 events=[]"
    ),
    "queue_condition_create|denied": (
        "outcome=rejected message='The database rejected the project update.' commit=False tokens=() conflict=no authoritative=no created=() | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "queue_condition_create|conflict": (
        "outcome=conflict message='stale' commit=False tokens=() conflict=yes authoritative=no created=() | "
        "calls=0 requests=['condition_folder:f1@7,condition_type:3@None,condition_types_collection:database@None,conditions_collection:7@7,layer:40@7'] records=0 values=[None] verify=0 reloads=0 events=[]"
    ),
    "queue_condition_create|unknown": (
        "outcome=commit_status_unknown message='The database rejected the project update.' commit=True tokens=('lease-1',) conflict=no authoritative=no created=() | "
        "calls=1 requests=['condition_folder:f1@7,condition_type:3@None,condition_types_collection:database@None,conditions_collection:7@7,layer:40@7'] records=2 values=[None] verify=0 reloads=0 events=[]"
    ),
    "queue_condition_create plain|denied": (
        "outcome=rejected message='The database rejected the project update.' commit=False tokens=() conflict=no authoritative=no created=() | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "queue_condition_create plain|conflict": (
        "outcome=conflict message='stale' commit=False tokens=() conflict=yes authoritative=no created=() | "
        "calls=0 requests=['conditions_collection:7@7'] records=0 values=[None] verify=0 reloads=0 events=[]"
    ),
    "queue_condition_create plain|unknown": (
        "outcome=commit_status_unknown message='The database rejected the project update.' commit=True tokens=('lease-1',) conflict=no authoritative=no created=() | "
        "calls=1 requests=['conditions_collection:7@7'] records=2 values=[None] verify=0 reloads=0 events=[]"
    ),
    "queue_conditions_delete|denied": (
        "outcome=rejected message='The database rejected the project update.' commit=False tokens=() conflict=no authoritative=no created=() | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "queue_conditions_delete|conflict": (
        "outcome=conflict message='stale' commit=False tokens=() conflict=yes authoritative=no created=() | "
        "calls=0 requests=['condition:c1@7,condition:c2@7,conditions_collection:7@7'] records=0 values=[None] verify=0 reloads=0 events=[]"
    ),
    "queue_conditions_delete|unknown": (
        "outcome=commit_status_unknown message='The database rejected the project update.' commit=True tokens=('lease-1',) conflict=no authoritative=no created=() | "
        "calls=1 requests=['condition:c1@7,condition:c2@7,conditions_collection:7@7'] records=3 values=[None] verify=0 reloads=0 events=[]"
    ),
    "queue_conditions_duplicate|denied": (
        "outcome=rejected message='The database rejected the project update.' commit=False tokens=() conflict=no authoritative=no created=() | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "queue_conditions_duplicate|conflict": (
        "outcome=conflict message='stale' commit=False tokens=() conflict=yes authoritative=no created=() | "
        "calls=0 requests=['condition:c1@7,condition:c2@7,condition_folder:f1@7,condition_type:3@None,condition_types_collection:database@None,conditions_collection:7@7'] records=0 values=[None] verify=0 reloads=0 events=[]"
    ),
    "queue_conditions_duplicate|unknown": (
        "outcome=commit_status_unknown message='The database rejected the project update.' commit=True tokens=('lease-1',) conflict=no authoritative=no created=() | "
        "calls=3 requests=['condition:c1@7,condition:c2@7,condition_folder:f1@7,condition_type:3@None,condition_types_collection:database@None,conditions_collection:7@7'] records=3 values=[None] verify=0 reloads=0 events=[]"
    ),
    "queue_conditions_update|denied": (
        "outcome=rejected message='The database rejected the project update.' commit=False tokens=() conflict=no authoritative=no created=() | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "queue_conditions_update|conflict": (
        "outcome=conflict message='stale' commit=False tokens=() conflict=yes authoritative=no created=() | "
        "calls=0 requests=['condition:c1@7,condition:c2@7,condition_folder:f1@7,condition_type:3@None,condition_types_collection:database@None,layer:40@7'] records=0 values=[None] verify=0 reloads=0 events=[]"
    ),
    "queue_conditions_update|unknown": (
        "outcome=commit_status_unknown message='The database rejected the project update.' commit=True tokens=('lease-1',) conflict=no authoritative=no created=() | "
        "calls=2 requests=['condition:c1@7,condition:c2@7,condition_folder:f1@7,condition_type:3@None,condition_types_collection:database@None,layer:40@7'] records=2 values=[None] verify=0 reloads=0 events=[]"
    ),
    "queue_conditions_update clearing type|denied": (
        "outcome=rejected message='The database rejected the project update.' commit=False tokens=() conflict=no authoritative=no created=() | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "queue_conditions_update clearing type|conflict": (
        "outcome=conflict message='stale' commit=False tokens=() conflict=yes authoritative=no created=() | "
        "calls=0 requests=['condition:c1@7,condition_types_collection:database@None'] records=0 values=[None] verify=0 reloads=0 events=[]"
    ),
    "queue_conditions_update clearing type|unknown": (
        "outcome=commit_status_unknown message='The database rejected the project update.' commit=True tokens=('lease-1',) conflict=no authoritative=no created=() | "
        "calls=1 requests=['condition:c1@7,condition_types_collection:database@None'] records=1 values=[None] verify=0 reloads=0 events=[]"
    ),
    "queue_conditions_renumber|denied": (
        "outcome=rejected message='The database rejected the project update.' commit=False tokens=() conflict=no authoritative=no created=() | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "queue_conditions_renumber|conflict": (
        "outcome=conflict message='stale' commit=False tokens=() conflict=yes authoritative=no created=() | "
        "calls=0 requests=['condition:c1@7,condition:c2@7,conditions_collection:7@7'] records=0 values=[None] verify=0 reloads=0 events=[]"
    ),
    "queue_conditions_renumber|unknown": (
        "outcome=commit_status_unknown message='The database rejected the project update.' commit=True tokens=('lease-1',) conflict=no authoritative=no created=() | "
        "calls=1 requests=['condition:c1@7,condition:c2@7,conditions_collection:7@7'] records=3 values=[None] verify=0 reloads=0 events=[]"
    ),
    "queue_condition_folder_create|denied": (
        "outcome=rejected message='The database rejected the project update.' commit=False tokens=() conflict=no authoritative=no created=() | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "queue_condition_folder_create|conflict": (
        "outcome=conflict message='stale' commit=False tokens=() conflict=yes authoritative=no created=() | "
        "calls=0 requests=['condition_folder:f1@7,conditions_collection:7@7'] records=0 values=[None] verify=0 reloads=0 events=[]"
    ),
    "queue_condition_folder_create|unknown": (
        "outcome=commit_status_unknown message='The database rejected the project update.' commit=True tokens=('lease-1',) conflict=no authoritative=no created=() | "
        "calls=1 requests=['condition_folder:f1@7,conditions_collection:7@7'] records=2 values=[None] verify=0 reloads=0 events=[]"
    ),
    "queue_condition_folder_create root|denied": (
        "outcome=rejected message='The database rejected the project update.' commit=False tokens=() conflict=no authoritative=no created=() | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "queue_condition_folder_create root|conflict": (
        "outcome=conflict message='stale' commit=False tokens=() conflict=yes authoritative=no created=() | "
        "calls=0 requests=['conditions_collection:7@7'] records=0 values=[None] verify=0 reloads=0 events=[]"
    ),
    "queue_condition_folder_create root|unknown": (
        "outcome=commit_status_unknown message='The database rejected the project update.' commit=True tokens=('lease-1',) conflict=no authoritative=no created=() | "
        "calls=1 requests=['conditions_collection:7@7'] records=2 values=[None] verify=0 reloads=0 events=[]"
    ),
    "queue_condition_folder_rename|denied": (
        "outcome=rejected message='The database rejected the project update.' commit=False tokens=() conflict=no authoritative=no created=() | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "queue_condition_folder_rename|conflict": (
        "outcome=conflict message='stale' commit=False tokens=() conflict=yes authoritative=no created=() | "
        "calls=0 requests=['condition_folder:f1@7'] records=0 values=[None] verify=0 reloads=0 events=[]"
    ),
    "queue_condition_folder_rename|unknown": (
        "outcome=commit_status_unknown message='The database rejected the project update.' commit=True tokens=('lease-1',) conflict=no authoritative=no created=() | "
        "calls=1 requests=['condition_folder:f1@7'] records=1 values=[None] verify=0 reloads=0 events=[]"
    ),
    "queue_condition_folders_delete|denied": (
        "outcome=rejected message='The database rejected the project update.' commit=False tokens=() conflict=no authoritative=no created=() | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "queue_condition_folders_delete|conflict": (
        "outcome=conflict message='stale' commit=False tokens=() conflict=yes authoritative=no created=() | "
        "calls=0 requests=['condition_folder:f1@7,condition_folder:f2@7,conditions_collection:7@7'] records=0 values=[None] verify=0 reloads=0 events=[]"
    ),
    "queue_condition_folders_delete|unknown": (
        "outcome=commit_status_unknown message='The database rejected the project update.' commit=True tokens=('lease-1',) conflict=no authoritative=no created=() | "
        "calls=1 requests=['condition_folder:f1@7,condition_folder:f2@7,conditions_collection:7@7'] records=3 values=[None] verify=0 reloads=0 events=[]"
    ),
    "queue_layer_insert|denied": (
        "outcome=rejected message='The database rejected the project update.' commit=False tokens=() conflict=no authoritative=no created=() | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "queue_layer_insert|conflict": (
        "outcome=conflict message='stale' commit=False tokens=() conflict=yes authoritative=no created=() | "
        "calls=0 requests=['layers_collection:7@7'] records=0 values=[None] verify=0 reloads=0 events=[]"
    ),
    "queue_layer_insert|unknown": (
        "outcome=commit_status_unknown message='The database rejected the project update.' commit=True tokens=('lease-1',) conflict=no authoritative=no created=() | "
        "calls=1 requests=['layers_collection:7@7'] records=2 values=[None] verify=0 reloads=0 events=[]"
    ),
    "queue_layer_delete|denied": (
        "outcome=rejected message='The database rejected the project update.' commit=False tokens=() conflict=no authoritative=no created=() | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "queue_layer_delete|conflict": (
        "outcome=conflict message='stale' commit=False tokens=() conflict=yes authoritative=no created=() | "
        "calls=0 requests=['layer:40@7,layers_collection:7@7'] records=0 values=[None] verify=0 reloads=0 events=[]"
    ),
    "queue_layer_delete|unknown": (
        "outcome=commit_status_unknown message='The database rejected the project update.' commit=True tokens=('lease-1',) conflict=no authoritative=no created=() | "
        "calls=1 requests=['layer:40@7,layers_collection:7@7'] records=2 values=[None] verify=0 reloads=0 events=[]"
    ),
    "queue_layers_delete|denied": (
        "outcome=rejected message='The database rejected the project update.' commit=False tokens=() conflict=no authoritative=no created=() | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "queue_layers_delete|conflict": (
        "outcome=conflict message='stale' commit=False tokens=() conflict=yes authoritative=no created=() | "
        "calls=0 requests=['layer:40@7,layer:41@7,layers_collection:7@7'] records=0 values=[None] verify=0 reloads=0 events=[]"
    ),
    "queue_layers_delete|unknown": (
        "outcome=commit_status_unknown message='The database rejected the project update.' commit=True tokens=('lease-1',) conflict=no authoritative=no created=() | "
        "calls=2 requests=['layer:40@7,layer:41@7,layers_collection:7@7'] records=3 values=[None] verify=0 reloads=0 events=[]"
    ),
    "queue_layer_reorder|denied": (
        "outcome=rejected message='The database rejected the project update.' commit=False tokens=() conflict=no authoritative=no created=() | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "queue_layer_reorder|conflict": (
        "outcome=conflict message='stale' commit=False tokens=() conflict=yes authoritative=no created=() | "
        "calls=0 requests=['layer:40@7,layer:41@7,layers_collection:7@7'] records=0 values=[None] verify=0 reloads=0 events=[]"
    ),
    "queue_layer_reorder|unknown": (
        "outcome=commit_status_unknown message='The database rejected the project update.' commit=True tokens=('lease-1',) conflict=no authoritative=no created=() | "
        "calls=1 requests=['layer:40@7,layer:41@7,layers_collection:7@7'] records=3 values=[None] verify=0 reloads=0 events=[]"
    ),
    "queue_all_layers_show|denied": (
        "outcome=rejected message='The database rejected the project update.' commit=False tokens=() conflict=no authoritative=no created=() | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "queue_all_layers_show|conflict": (
        "outcome=conflict message='stale' commit=False tokens=() conflict=yes authoritative=no created=() | "
        "calls=0 requests=['layers_collection:7@7'] records=0 values=[None] verify=0 reloads=0 events=[]"
    ),
    "queue_all_layers_show|unknown": (
        "outcome=commit_status_unknown message='The database rejected the project update.' commit=True tokens=('lease-1',) conflict=no authoritative=no created=() | "
        "calls=1 requests=['layers_collection:7@7'] records=1 values=[None] verify=0 reloads=0 events=[]"
    ),
    "queue_layer_rename|denied": (
        "outcome=rejected message='The database rejected the project update.' commit=False tokens=() conflict=no authoritative=no created=() | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "queue_layer_rename|conflict": (
        "outcome=conflict message='stale' commit=False tokens=() conflict=yes authoritative=no created=() | "
        "calls=0 requests=['layer:40@7'] records=0 values=[None] verify=0 reloads=0 events=[]"
    ),
    "queue_layer_rename|unknown": (
        "outcome=commit_status_unknown message='The database rejected the project update.' commit=True tokens=('lease-1',) conflict=no authoritative=no created=() | "
        "calls=1 requests=['layer:40@7'] records=1 values=[None] verify=0 reloads=0 events=[]"
    ),
    "queue_project_import|denied": (
        "outcome=rejected message='The database rejected the project update.' commit=False tokens=() conflict=no authoritative=no created=() | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "queue_project_import|conflict": (
        "outcome=conflict message='stale' commit=False tokens=() conflict=yes authoritative=no created=() | "
        "calls=0 requests=['condition_types_collection:database@None,employees_collection:database@None,job_statuses_collection:database@None,pay_classes_collection:database@None,project:9@None,project_bids:9@None'] records=0 values=[None] verify=0 reloads=0 events=[]"
    ),
    "queue_project_import|unknown": (
        "outcome=commit_status_unknown message='The database rejected the project update.' commit=True tokens=('lease-1',) conflict=no authoritative=no created=() | "
        "calls=0 requests=['condition_types_collection:database@None,employees_collection:database@None,job_statuses_collection:database@None,pay_classes_collection:database@None,project:9@None,project_bids:9@None'] records=0 values=[None] verify=0 reloads=0 events=[]"
    ),
    "queue_project_import orphan|denied": (
        "outcome=rejected message='The database rejected the project update.' commit=False tokens=() conflict=no authoritative=no created=() | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "queue_project_import orphan|conflict": (
        "outcome=conflict message='stale' commit=False tokens=() conflict=yes authoritative=no created=() | "
        "calls=0 requests=['condition_types_collection:database@None,employees_collection:database@None,job_statuses_collection:database@None,pay_classes_collection:database@None,project_bids:orphan@None'] records=0 values=[None] verify=0 reloads=0 events=[]"
    ),
    "queue_project_import orphan|unknown": (
        "outcome=commit_status_unknown message='The database rejected the project update.' commit=True tokens=('lease-1',) conflict=no authoritative=no created=() | "
        "calls=0 requests=['condition_types_collection:database@None,employees_collection:database@None,job_statuses_collection:database@None,pay_classes_collection:database@None,project_bids:orphan@None'] records=0 values=[None] verify=0 reloads=0 events=[]"
    ),
}
_PLAN_QUEUE_SCENARIO_EXPECTED = {
    "placement|denied": (
        "outcome=rejected message='The database rejected the placement.' commit=False tokens=() conflict=no authoritative=no created=() | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "placement|conflict": (
        "outcome=conflict message='stale' commit=False tokens=() conflict=yes authoritative=no created=() | "
        "calls=0 requests=['area:5@7,condition:10@7,condition:11@7,page:20@7,page:21@7,takeoff:30@7,takeoffs_collection:7@7'] records=0 values=[None] verify=0 reloads=0 events=[]"
    ),
    "placement|unknown": (
        "outcome=commit_status_unknown message='The database rejected the placement.' commit=True tokens=('lease-1',) conflict=no authoritative=no created=() | "
        "calls=1 requests=['area:5@7,condition:10@7,condition:11@7,page:20@7,page:21@7,takeoff:30@7,takeoffs_collection:7@7'] records=3 values=[None] verify=0 reloads=0 events=[]"
    ),
    "delete mixed|denied": (
        "outcome=rejected message='The database rejected deletion.' commit=False tokens=() conflict=no authoritative=no created=() | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "delete mixed|conflict": (
        "outcome=conflict message='stale' commit=False tokens=() conflict=yes authoritative=no created=() | "
        "calls=0 requests=['annotation:line/a2@7,annotation:rect/a1@7,annotations_collection:7@7,condition:10@7,page:20@7,page:21@7,takeoff:30@7,takeoff:31@7,takeoffs_collection:7@7'] records=0 values=[None] verify=0 reloads=0 events=[]"
    ),
    "delete mixed|unknown": (
        "outcome=commit_status_unknown message='The database rejected deletion.' commit=True tokens=('lease-1',) conflict=no authoritative=no created=() | "
        "calls=2 requests=['annotation:line/a2@7,annotation:rect/a1@7,annotations_collection:7@7,condition:10@7,page:20@7,page:21@7,takeoff:30@7,takeoff:31@7,takeoffs_collection:7@7'] records=6 values=[None] verify=1 reloads=0 events=[]"
    ),
    "delete takeoffs only|denied": (
        "outcome=rejected message='The database rejected deletion.' commit=False tokens=() conflict=no authoritative=no created=() | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "delete takeoffs only|conflict": (
        "outcome=conflict message='stale' commit=False tokens=() conflict=yes authoritative=no created=() | "
        "calls=0 requests=['page:20@7,takeoff:30@7,takeoffs_collection:7@7'] records=0 values=[None] verify=0 reloads=0 events=[]"
    ),
    "delete takeoffs only|unknown": (
        "outcome=commit_status_unknown message='The database rejected deletion.' commit=True tokens=('lease-1',) conflict=no authoritative=no created=() | "
        "calls=1 requests=['page:20@7,takeoff:30@7,takeoffs_collection:7@7'] records=2 values=[None] verify=1 reloads=0 events=[]"
    ),
    "delete annotations only|denied": (
        "outcome=rejected message='The database rejected deletion.' commit=False tokens=() conflict=no authoritative=no created=() | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "delete annotations only|conflict": (
        "outcome=conflict message='stale' commit=False tokens=() conflict=yes authoritative=no created=() | "
        "calls=0 requests=['annotation:rect/a1@7,annotations_collection:7@7'] records=0 values=[None] verify=0 reloads=0 events=[]"
    ),
    "delete annotations only|unknown": (
        "outcome=commit_status_unknown message='The database rejected deletion.' commit=True tokens=('lease-1',) conflict=no authoritative=no created=() | "
        "calls=1 requests=['annotation:rect/a1@7,annotations_collection:7@7'] records=2 values=[None] verify=1 reloads=0 events=[]"
    ),
    "geometry mixed|denied": (
        "outcome=rejected message='The database rejected the geometry update.' commit=False tokens=() conflict=no authoritative=no created=() | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "geometry mixed|conflict": (
        "outcome=conflict message='stale' commit=False tokens=() conflict=yes authoritative=no created=() | "
        "calls=0 requests=['annotation:rect/a1@7,condition:10@7,page:20@7,page:21@7,takeoff:30@7,takeoff:31@7,takeoff:32@7'] records=0 values=[None] verify=0 reloads=0 events=[]"
    ),
    "geometry mixed|unknown": (
        "outcome=commit_status_unknown message='The database rejected the geometry update.' commit=True tokens=('lease-1',) conflict=no authoritative=no created=() | "
        "calls=3 requests=['annotation:rect/a1@7,condition:10@7,page:20@7,page:21@7,takeoff:30@7,takeoff:31@7,takeoff:32@7'] records=4 values=[None] verify=1 reloads=0 events=[]"
    ),
    "geometry rotation only|denied": (
        "outcome=rejected message='The database rejected the geometry update.' commit=False tokens=() conflict=no authoritative=no created=() | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "geometry rotation only|conflict": (
        "outcome=conflict message='stale' commit=False tokens=() conflict=yes authoritative=no created=() | "
        "calls=0 requests=['page:21@7,takeoff:32@7'] records=0 values=[None] verify=0 reloads=0 events=[]"
    ),
    "geometry rotation only|unknown": (
        "outcome=commit_status_unknown message='The database rejected the geometry update.' commit=True tokens=('lease-1',) conflict=no authoritative=no created=() | "
        "calls=1 requests=['page:21@7,takeoff:32@7'] records=1 values=[None] verify=1 reloads=0 events=[]"
    ),
    "geometry annotations only|denied": (
        "outcome=rejected message='The database rejected the geometry update.' commit=False tokens=() conflict=no authoritative=no created=() | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "geometry annotations only|conflict": (
        "outcome=conflict message='stale' commit=False tokens=() conflict=yes authoritative=no created=() | "
        "calls=0 requests=['annotation:line/a1@7'] records=0 values=[None] verify=0 reloads=0 events=[]"
    ),
    "geometry annotations only|unknown": (
        "outcome=commit_status_unknown message='The database rejected the geometry update.' commit=True tokens=('lease-1',) conflict=no authoritative=no created=() | "
        "calls=1 requests=['annotation:line/a1@7'] records=1 values=[None] verify=1 reloads=0 events=[]"
    ),
    "properties takeoff_text|denied": (
        "outcome=rejected message='The database rejected the property update.' commit=False tokens=() conflict=no authoritative=no created=() | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "properties takeoff_text|conflict": (
        "outcome=conflict message='stale' commit=False tokens=() conflict=yes authoritative=no created=() | "
        "calls=0 requests=['page:20@7,takeoff:30@7,takeoff:31@7'] records=0 values=[None] verify=0 reloads=0 events=[]"
    ),
    "properties takeoff_text|unknown": (
        "outcome=commit_status_unknown message='The database rejected the property update.' commit=True tokens=('lease-1',) conflict=no authoritative=no created=() | "
        "calls=1 requests=['page:20@7,takeoff:30@7,takeoff:31@7'] records=1 values=[None] verify=1 reloads=0 events=[]"
    ),
    "properties takeoff_area|denied": (
        "outcome=rejected message='The database rejected the property update.' commit=False tokens=() conflict=no authoritative=no created=() | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "properties takeoff_area|conflict": (
        "outcome=conflict message='stale' commit=False tokens=() conflict=yes authoritative=no created=() | "
        "calls=0 requests=['condition:10@7,takeoff:30@7,takeoff:31@7,takeoff:32@7'] records=0 values=[None] verify=0 reloads=0 events=[]"
    ),
    "properties takeoff_area|unknown": (
        "outcome=commit_status_unknown message='The database rejected the property update.' commit=True tokens=('lease-1',) conflict=no authoritative=no created=() | "
        "calls=2 requests=['condition:10@7,takeoff:30@7,takeoff:31@7,takeoff:32@7'] records=3 values=[None] verify=1 reloads=0 events=[]"
    ),
    "properties takeoff_condition|denied": (
        "outcome=rejected message='The database rejected the property update.' commit=False tokens=() conflict=no authoritative=no created=() | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "properties takeoff_condition|conflict": (
        "outcome=conflict message='stale' commit=False tokens=() conflict=yes authoritative=no created=() | "
        "calls=0 requests=['takeoff:30@7,takeoff:31@7,takeoff:32@7'] records=0 values=[None] verify=0 reloads=0 events=[]"
    ),
    "properties takeoff_condition|unknown": (
        "outcome=commit_status_unknown message='The database rejected the property update.' commit=True tokens=('lease-1',) conflict=no authoritative=no created=() | "
        "calls=1 requests=['takeoff:30@7,takeoff:31@7,takeoff:32@7'] records=2 values=[None] verify=1 reloads=0 events=[]"
    ),
    "properties takeoff_negative|denied": (
        "outcome=rejected message='The database rejected the property update.' commit=False tokens=() conflict=no authoritative=no created=() | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "properties takeoff_negative|conflict": (
        "outcome=conflict message='stale' commit=False tokens=() conflict=yes authoritative=no created=() | "
        "calls=0 requests=['takeoff:30@7,takeoff:31@7,takeoff:32@7'] records=0 values=[None] verify=0 reloads=0 events=[]"
    ),
    "properties takeoff_negative|unknown": (
        "outcome=commit_status_unknown message='The database rejected the property update.' commit=True tokens=('lease-1',) conflict=no authoritative=no created=() | "
        "calls=2 requests=['takeoff:30@7,takeoff:31@7,takeoff:32@7'] records=2 values=[None] verify=1 reloads=0 events=[]"
    ),
    "properties takeoff_curve|denied": (
        "outcome=rejected message='The database rejected the property update.' commit=False tokens=() conflict=no authoritative=no created=() | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "properties takeoff_curve|conflict": (
        "outcome=conflict message='stale' commit=False tokens=() conflict=yes authoritative=no created=() | "
        "calls=0 requests=['page:20@7,page:21@7,takeoff:30@7,takeoff:31@7'] records=0 values=[None] verify=0 reloads=0 events=[]"
    ),
    "properties takeoff_curve|unknown": (
        "outcome=commit_status_unknown message='The database rejected the property update.' commit=True tokens=('lease-1',) conflict=no authoritative=no created=() | "
        "calls=1 requests=['page:20@7,page:21@7,takeoff:30@7,takeoff:31@7'] records=1 values=[None] verify=1 reloads=0 events=[]"
    ),
    "properties annotation_text|denied": (
        "outcome=rejected message='The database rejected the property update.' commit=False tokens=() conflict=no authoritative=no created=() | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "properties annotation_text|conflict": (
        "outcome=conflict message='stale' commit=False tokens=() conflict=yes authoritative=no created=() | "
        "calls=0 requests=['annotation:rect/a1@7'] records=0 values=[None] verify=0 reloads=0 events=[]"
    ),
    "properties annotation_text|unknown": (
        "outcome=commit_status_unknown message='The database rejected the property update.' commit=True tokens=('lease-1',) conflict=no authoritative=no created=() | "
        "calls=1 requests=['annotation:rect/a1@7'] records=1 values=[None] verify=1 reloads=0 events=[]"
    ),
    "properties annotation_style|denied": (
        "outcome=rejected message='The database rejected the property update.' commit=False tokens=() conflict=no authoritative=no created=() | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "properties annotation_style|conflict": (
        "outcome=conflict message='stale' commit=False tokens=() conflict=yes authoritative=no created=() | "
        "calls=0 requests=['annotation:rect/a1@7'] records=0 values=[None] verify=0 reloads=0 events=[]"
    ),
    "properties annotation_style|unknown": (
        "outcome=commit_status_unknown message='The database rejected the property update.' commit=True tokens=('lease-1',) conflict=no authoritative=no created=() | "
        "calls=1 requests=['annotation:rect/a1@7'] records=1 values=[None] verify=1 reloads=0 events=[]"
    ),
    "paste same bid|denied": (
        "outcome=rejected message='The database rejected paste.' commit=False tokens=() conflict=no authoritative=no created=() | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "paste same bid|conflict": (
        "outcome=conflict message='stale' commit=False tokens=() conflict=yes authoritative=no created=() | "
        "calls=0 requests=['annotations_collection:7@7,condition:c1@7,page:p1@7,takeoffs_collection:7@7'] records=0 values=[None] verify=0 reloads=0 events=[]"
    ),
    "paste same bid|unknown": (
        "outcome=commit_status_unknown message='The database rejected paste.' commit=True tokens=('lease-1',) conflict=no authoritative=no created=() | "
        "calls=4 requests=['annotations_collection:7@7,condition:c1@7,page:p1@7,takeoffs_collection:7@7'] records=6 values=[None] verify=0 reloads=0 events=[]"
    ),
    "paste cross bid|denied": (
        "outcome=rejected message='The database rejected paste.' commit=False tokens=() conflict=no authoritative=no created=() | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "paste cross bid|conflict": (
        "outcome=conflict message='stale' commit=False tokens=() conflict=yes authoritative=no created=() | "
        "calls=0 requests=['annotations_collection:7@7,condition:10@7,conditions_collection:7@7,page:p1@7,takeoffs_collection:7@7'] records=0 values=[None] verify=0 reloads=0 events=[]"
    ),
    "paste cross bid|unknown": (
        "outcome=commit_status_unknown message='The database rejected paste.' commit=True tokens=('lease-1',) conflict=no authoritative=no created=() | "
        "calls=5 requests=['annotations_collection:7@7,condition:10@7,conditions_collection:7@7,page:p1@7,takeoffs_collection:7@7'] records=8 values=[None] verify=0 reloads=0 events=[]"
    ),
    "page scale|denied": (
        "outcome=rejected message='The database rejected the page setting update.' commit=False tokens=() conflict=no authoritative=no created=() | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "page scale|conflict": (
        "outcome=conflict message='stale' commit=False tokens=() conflict=yes authoritative=no created=() | "
        "calls=0 requests=['page:20@7,page:21@7'] records=0 values=[None] verify=0 reloads=0 events=[]"
    ),
    "page scale|unknown": (
        "outcome=commit_status_unknown message='The database rejected the page setting update.' commit=True tokens=('lease-1',) conflict=no authoritative=no created=() | "
        "calls=3 requests=['page:20@7,page:21@7'] records=2 values=[None] verify=0 reloads=0 events=[]"
    ),
    "page show_mode|denied": (
        "outcome=rejected message='The database rejected the page setting update.' commit=False tokens=() conflict=no authoritative=no created=() | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "page show_mode|conflict": (
        "outcome=conflict message='stale' commit=False tokens=() conflict=yes authoritative=no created=() | "
        "calls=0 requests=['page:20@7'] records=0 values=[None] verify=0 reloads=0 events=[]"
    ),
    "page show_mode|unknown": (
        "outcome=commit_status_unknown message='The database rejected the page setting update.' commit=True tokens=('lease-1',) conflict=no authoritative=no created=() | "
        "calls=1 requests=['page:20@7'] records=1 values=[None] verify=0 reloads=0 events=[]"
    ),
    "page overlay_image|denied": (
        "outcome=rejected message='The database rejected the page setting update.' commit=False tokens=() conflict=no authoritative=no created=() | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "page overlay_image|conflict": (
        "outcome=conflict message='stale' commit=False tokens=() conflict=yes authoritative=no created=() | "
        "calls=0 requests=['page:20@7'] records=0 values=[None] verify=0 reloads=0 events=[]"
    ),
    "page overlay_image|unknown": (
        "outcome=commit_status_unknown message='The database rejected the page setting update.' commit=True tokens=('lease-1',) conflict=no authoritative=no created=() | "
        "calls=1 requests=['page:20@7'] records=1 values=[None] verify=0 reloads=0 events=[]"
    ),
    "page overlay_rect|denied": (
        "outcome=rejected message='The database rejected the page setting update.' commit=False tokens=() conflict=no authoritative=no created=() | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "page overlay_rect|conflict": (
        "outcome=conflict message='stale' commit=False tokens=() conflict=yes authoritative=no created=() | "
        "calls=0 requests=['page:20@7'] records=0 values=[None] verify=0 reloads=0 events=[]"
    ),
    "page overlay_rect|unknown": (
        "outcome=commit_status_unknown message='The database rejected the page setting update.' commit=True tokens=('lease-1',) conflict=no authoritative=no created=() | "
        "calls=1 requests=['page:20@7'] records=1 values=[None] verify=0 reloads=0 events=[]"
    ),
    "page invert|denied": (
        "outcome=rejected message='The database rejected the page setting update.' commit=False tokens=() conflict=no authoritative=no created=() | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "page invert|conflict": (
        "outcome=conflict message='stale' commit=False tokens=() conflict=yes authoritative=no created=() | "
        "calls=0 requests=['page:20@7'] records=0 values=[None] verify=0 reloads=0 events=[]"
    ),
    "page invert|unknown": (
        "outcome=commit_status_unknown message='The database rejected the page setting update.' commit=True tokens=('lease-1',) conflict=no authoritative=no created=() | "
        "calls=1 requests=['page:20@7'] records=1 values=[None] verify=0 reloads=0 events=[]"
    ),
    "page bitonal|denied": (
        "outcome=rejected message='The database rejected the page setting update.' commit=False tokens=() conflict=no authoritative=no created=() | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "page bitonal|conflict": (
        "outcome=conflict message='stale' commit=False tokens=() conflict=yes authoritative=no created=() | "
        "calls=0 requests=['page:20@7'] records=0 values=[None] verify=0 reloads=0 events=[]"
    ),
    "page bitonal|unknown": (
        "outcome=commit_status_unknown message='The database rejected the page setting update.' commit=True tokens=('lease-1',) conflict=no authoritative=no created=() | "
        "calls=1 requests=['page:20@7'] records=1 values=[None] verify=0 reloads=0 events=[]"
    ),
    "page image_adjustments|denied": (
        "outcome=rejected message='The database rejected the page setting update.' commit=False tokens=() conflict=no authoritative=no created=() | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "page image_adjustments|conflict": (
        "outcome=conflict message='stale' commit=False tokens=() conflict=yes authoritative=no created=() | "
        "calls=0 requests=['page:20@7,page:21@7'] records=0 values=[None] verify=0 reloads=0 events=[]"
    ),
    "page image_adjustments|unknown": (
        "outcome=commit_status_unknown message='The database rejected the page setting update.' commit=True tokens=('lease-1',) conflict=no authoritative=no created=() | "
        "calls=1 requests=['page:20@7,page:21@7'] records=2 values=[None] verify=0 reloads=0 events=[]"
    ),
    "page area|denied": (
        "outcome=rejected message='The database rejected the page setting update.' commit=False tokens=() conflict=no authoritative=no created=() | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "page area|conflict": (
        "outcome=conflict message='stale' commit=False tokens=() conflict=yes authoritative=no created=() | "
        "calls=0 requests=['page:20@7'] records=0 values=[None] verify=0 reloads=0 events=[]"
    ),
    "page area|unknown": (
        "outcome=commit_status_unknown message='The database rejected the page setting update.' commit=True tokens=('lease-1',) conflict=no authoritative=no created=() | "
        "calls=1 requests=['page:20@7'] records=1 values=[None] verify=0 reloads=0 events=[]"
    ),
    "page name|denied": (
        "outcome=rejected message='The database rejected the page setting update.' commit=False tokens=() conflict=no authoritative=no created=() | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "page name|conflict": (
        "outcome=conflict message='stale' commit=False tokens=() conflict=yes authoritative=no created=() | "
        "calls=0 requests=['page:20@7'] records=0 values=[None] verify=0 reloads=0 events=[]"
    ),
    "page name|unknown": (
        "outcome=commit_status_unknown message='The database rejected the page setting update.' commit=True tokens=('lease-1',) conflict=no authoritative=no created=() | "
        "calls=1 requests=['page:20@7'] records=1 values=[None] verify=0 reloads=0 events=[]"
    ),
    "page layer_show|denied": (
        "outcome=rejected message='The database rejected the page setting update.' commit=False tokens=() conflict=no authoritative=no created=() | "
        "calls=0 requests=[] records=0 values=[] verify=0 reloads=0 events=[]"
    ),
    "page layer_show|conflict": (
        "outcome=conflict message='stale' commit=False tokens=() conflict=yes authoritative=no created=() | "
        "calls=0 requests=['layer:40@7,layer:41@7'] records=0 values=[None] verify=0 reloads=0 events=[]"
    ),
    "page layer_show|unknown": (
        "outcome=commit_status_unknown message='The database rejected the page setting update.' commit=True tokens=('lease-1',) conflict=no authoritative=no created=() | "
        "calls=2 requests=['layer:40@7,layer:41@7'] records=2 values=[None] verify=0 reloads=0 events=[]"
    ),
}


class ProjectWriteCommandContractTests(unittest.TestCase):
    def test_local_commands_pin_routing_resources_records_and_refresh(self):
        refresh = (
            "event DatabaseRefreshedEvent {'file_path': 'C:/jobs/test.mdb', "
            "'image_sources_unchanged': False, 'mesh_scene_unchanged': False, "
            "'page_scale_uids': ()}"
        )
        self.assertEqual(
            {label for label, _results, _command in _local_rows()},
            set(_LOCAL_EXPECTED),
        )
        for label, results, command in _local_rows():
            with self.subTest(command=label):
                harness = _Harness(results)
                report = harness.local_report(command(harness.service))
                self.assertEqual(
                    report.replace(refresh, "event REFRESH") + "\n",
                    _LOCAL_EXPECTED[label],
                )

    def test_every_local_scenario_pins_exact_result_calls_requests_and_side_effects(
        self,
    ):
        for rows, expected, scenarios in (
            (_local_rows, _LOCAL_SCENARIO_EXPECTED, _SCENARIOS),
            (_plan_local_rows, _PLAN_LOCAL_SCENARIO_EXPECTED, _PLAN_SCENARIOS),
        ):
            labels = {row[0] for row in rows()}
            self.assertEqual({key.split("|")[0] for key in expected}, labels)
            self.assertEqual(len(expected), len(labels) * len(scenarios))
            for label in sorted(labels):
                for scenario in scenarios:
                    with self.subTest(command=label, scenario=scenario):
                        self.assertEqual(
                            _local_scenario_text(rows, label, scenario),
                            expected[f"{label}|{scenario}"],
                        )

    def test_every_queued_scenario_pins_outcome_provenance_and_side_effects(self):
        for rows, expected in (
            (_queue_rows, _QUEUE_SCENARIO_EXPECTED),
            (_plan_queue_rows, _PLAN_QUEUE_SCENARIO_EXPECTED),
        ):
            labels = {row[0] for row in rows()}
            self.assertEqual({key.split("|")[0] for key in expected}, labels)
            for label in sorted(labels):
                for scenario in ("denied", "conflict", "unknown"):
                    with self.subTest(command=label, scenario=scenario):
                        self.assertEqual(
                            _queue_scenario_text(rows, label, scenario),
                            expected[f"{label}|{scenario}"],
                        )

    def test_queued_commands_pin_request_scope_work_and_authoritative_result(self):
        self.assertEqual(
            {label for label, _results, _submit in _queue_rows()}, set(_QUEUE_EXPECTED)
        )
        for label, results, submit in _queue_rows():
            with self.subTest(command=label):
                harness = _Harness(results)
                sequence = submit(harness.service, lambda _result: None)
                self.assertEqual(sequence, 41)
                self.assertEqual(len(harness.provider.requests), 1)
                self.assertEqual(harness.calls, [], "queueing must not write")
                self.assertEqual(harness.executor.requests, [])
                self.assertEqual(harness.provider.options, [{}])
                self.assertEqual(harness.queue_report() + "\n", _QUEUE_EXPECTED[label])

    def test_queued_work_aborts_without_recording_when_the_use_case_fails(self):
        for label, results, submit in _queue_rows():
            with self.subTest(command=label):
                probe = _Harness(results)
                submit(probe.service, lambda _result: None)
                probe.queue_report()
                if not probe.calls:
                    continue  # project import: its work is an injected callable
                use_case, method = probe.calls[0][0], probe.calls[0][1]
                if use_case == "update_condition":
                    failure = UpdateConditionResultDto(success=False, error="rejected")
                else:
                    failure = None
                harness = _Harness({**results, (use_case, method): failure})
                submit(harness.service, lambda _result: None)
                _request, execute, _callback = harness.provider.requests[0]
                with self.assertRaises(RuntimeError):
                    execute()
                self.assertEqual(harness.executor.recorder.changes, [])

    def test_collaboration_routing_is_delegated_to_the_provider_verbatim(self):
        harness = _Harness()
        provider = harness.provider
        provider.cancelled = []
        provider.leases = []
        provider.cancel_queued_mutation = lambda database, operation: (
            provider.cancelled.append((database, operation)) or True
        )
        provider.request_local_edit = lambda *args, **kwargs: provider.leases.append(
            (args, kwargs)
        )
        provider.end_edit_lease = lambda handle: provider.leases.append(("end", handle))
        provider.uses_sql_collaboration = lambda database: database == "sql-db"
        self.assertIs(harness.service.uses_sql_collaboration_mutations("sql-db"), True)
        self.assertIs(
            harness.service.uses_sql_collaboration_mutations("access.mdb"), False
        )
        self.assertIs(
            harness.service.cancel_queued_sql_mutation("sql-db", "op-1"), True
        )
        self.assertEqual(provider.cancelled, [("sql-db", "op-1")])
        resource = ResourceRef("takeoff", "30", 7)
        dependency = ResourceRef("page", "20", 7)

        def callback(_result):
            return None

        harness.service.request_plan_edit_lease(
            "sql-db",
            (resource,),
            (dependency,),
            callback,
            operation_id="op-2",
            owning_surface="main-plan",
        )
        handle = object()
        harness.service.end_plan_edit_lease(handle)
        self.assertEqual(
            provider.leases,
            [
                (
                    ("sql-db", (resource,), callback),
                    {
                        "dependency_resources": (dependency,),
                        "operation_id": "op-2",
                        "owning_surface": "main-plan",
                    },
                ),
                ("end", handle),
            ],
        )


class ProjectWriteBatchOutcomeTests(unittest.TestCase):
    def test_batch_layer_deletes_report_failure_when_the_mutation_is_not_committed(
        self,
    ):
        database = _Harness.DATABASE
        for method, uids in (
            ("delete_layers", ["40", "41"]),
            ("delete_default_layers", ["40", "41"]),
        ):
            for status in (
                MutationOutcomeStatus.REJECTED,
                MutationOutcomeStatus.FAILED_BEFORE_COMMIT,
                MutationOutcomeStatus.CONFLICT,
                MutationOutcomeStatus.COMMIT_STATUS_UNKNOWN,
            ):
                with self.subTest(method=method, status=status):
                    harness = _Harness()
                    harness.executor.status = status
                    result = getattr(harness.service, method)(database, uids)
                    self.assertFalse(result)
                    self.assertFalse(result.any_success)
                    self.assertEqual(result.succeeded_uids, [])
                    self.assertEqual(result.failed_uids, uids)
                    self.assertEqual(result.requested_uids, uids)
                    self.assertEqual(
                        (harness.reloads, harness.events.published), ([], [])
                    )


class ProjectWritePlanContractTests(unittest.TestCase):
    REFRESH = (
        "event DatabaseRefreshedEvent {'file_path': 'C:/jobs/test.mdb', "
        "'image_sources_unchanged': False, 'mesh_scene_unchanged': False, "
        "'page_scale_uids': ()}"
    )

    def test_access_plan_commands_pin_preflight_resources_records_and_result(self):
        self.assertEqual(
            {label for label, _results, _command in _plan_local_rows()},
            set(_PLAN_LOCAL_EXPECTED),
        )
        for label, results, command in _plan_local_rows():
            with self.subTest(command=label):
                harness = _Harness(results, sql=False)
                report = harness.local_report(command(harness.service))
                self.assertEqual(
                    report.replace(self.REFRESH, "event REFRESH") + "\n",
                    _PLAN_LOCAL_EXPECTED[label],
                )

    def test_sql_plan_commands_pin_request_scope_preflight_work_and_result(self):
        self.assertEqual(
            {label for label, _results, _submit, _setup in _plan_queue_rows()},
            set(_PLAN_QUEUE_EXPECTED),
        )
        validated = {"placement", "paste same bid", "paste cross bid"}
        for label, results, submit, setup in _plan_queue_rows():
            with self.subTest(command=label):
                harness = _Harness(results)
                if setup:
                    setup(harness)
                self.assertEqual(submit(harness.service, lambda _result: None), 41)
                self.assertEqual(harness.calls, [], "queueing must not write")
                self.assertEqual(harness.executor.requests, [])
                self.assertEqual(harness.executor.verifications, [])
                self.assertEqual(
                    set(harness.provider.options[0]),
                    {"result_validator"} if label in validated else set(),
                )
                self.assertEqual(
                    harness.queue_report() + "\n", _PLAN_QUEUE_EXPECTED[label]
                )

    def test_access_plan_commands_refuse_sql_databases(self):
        for label, results, command in _plan_local_rows():
            with self.subTest(command=label):
                harness = _Harness(results, sql=True)
                with self.assertRaisesRegex(ValueError, "collaboration queue"):
                    command(harness.service)
                self.assertEqual(harness.calls, [])
                self.assertEqual(harness.executor.requests, [])

    def test_revoked_capability_rejects_plan_commands_before_any_preflight_or_write(
        self,
    ):
        for label, results, command in _plan_local_rows():
            with self.subTest(command=label, backend="access"):
                harness = _Harness(results, sql=False, editable=False)
                result = command(harness.service)
                self.assertEqual(result.outcome_status, MutationOutcomeStatus.REJECTED)
                self.assertIsNone(result.authoritative_result)
                self.assertIn("rejected", result.message)
                self.assertEqual(harness.calls, [])
                self.assertEqual(harness.executor.verifications, [])
                self.assertEqual((harness.reloads, harness.events.published), ([], []))
        for label, results, submit, setup in _plan_queue_rows():
            with self.subTest(command=label, backend="sql"):
                harness = _Harness(results, editable=False)
                if setup:
                    setup(harness)
                submit(harness.service, lambda _result: None)
                _request, execute, _callback = harness.provider.requests[0]
                execution = execute()
                self.assertEqual(
                    execution.outcome_status, MutationOutcomeStatus.REJECTED
                )
                self.assertIsNone(execution.authoritative_result)
                self.assertIn("rejected", execution.message)
                self.assertEqual(harness.calls, [])
                self.assertEqual(harness.executor.verifications, [])
                self.assertEqual(harness.executor.recorder.changes, [])

    def test_plan_work_stops_at_the_first_failed_use_case_without_recording(self):
        for label, results, command in _plan_local_rows():
            probe = _Harness(results, sql=False)
            command(probe.service)
            use_case, method = probe.calls[0][0], probe.calls[0][1]
            with self.subTest(command=label, backend="access"):
                failure = _failure_value(use_case, method)
                harness = _Harness({**results, (use_case, method): failure}, sql=False)
                result = command(harness.service)
                self.assertEqual(
                    result.outcome_status, MutationOutcomeStatus.FAILED_BEFORE_COMMIT
                )
                self.assertIsNone(result.authoritative_result)
                self.assertTrue(result.message)
                self.assertEqual(harness.executor.recorder.changes, [])
                self.assertEqual((harness.reloads, harness.events.published), ([], []))
        for label, results, submit, setup in _plan_queue_rows():
            probe = _Harness(results)
            if setup:
                setup(probe)
            submit(probe.service, lambda _result: None)
            probe.queue_report()
            use_case, method = probe.calls[0][0], probe.calls[0][1]
            with self.subTest(command=label, backend="sql"):
                failure = _failure_value(use_case, method)
                harness = _Harness({**results, (use_case, method): failure})
                if setup:
                    setup(harness)
                submit(harness.service, lambda _result: None)
                _request, execute, _callback = harness.provider.requests[0]
                with self.assertRaisesRegex(RuntimeError, "incomplete|did not create"):
                    execute()
                self.assertEqual(harness.executor.recorder.changes, [])

    def test_failed_preflight_prevents_every_plan_write(self):
        class Gone(RuntimeError):
            pass

        def explode(*_args, **_kwargs):
            raise Gone("selected item was deleted")

        for label, results, command in _plan_local_rows():
            harness = _Harness(results, sql=False)
            harness.executor.verify_plan_items_exist = explode
            with self.subTest(command=label, backend="access"):
                if label.startswith(("delete_local", "paste_local")):
                    continue  # Access delete/paste run no plan-item preflight.
                result = command(harness.service)
                self.assertEqual(
                    result.outcome_status, MutationOutcomeStatus.FAILED_BEFORE_COMMIT
                )
                self.assertEqual(result.message, "selected item was deleted")
                self.assertEqual(harness.calls, [])
        for label, results, submit, setup in _plan_queue_rows():
            if not label.startswith(("delete", "geometry", "properties")):
                continue
            with self.subTest(command=label, backend="sql"):
                harness = _Harness(results)
                if setup:
                    setup(harness)
                harness.executor.verify_plan_items_exist = explode
                submit(harness.service, lambda _result: None)
                _request, execute, _callback = harness.provider.requests[0]
                with self.assertRaises(Gone):
                    execute()
                self.assertEqual(harness.calls, [])
                self.assertEqual(harness.executor.recorder.changes, [])

    def test_queued_property_baselines_cover_every_guarded_resource(self):
        def submit(harness):
            return harness.service.queue_plan_properties(
                _Harness.DATABASE,
                "7",
                "takeoff_area",
                [("30", "5"), ("32", "0")],
                lambda _result: None,
                dependency_resources=(ResourceRef("area", "0", 7),),
            )

        harness = _Harness()
        harness.tokens.guard = True
        submit(harness)
        baseline = harness.tokens.expected_requests[-1][1]
        # The unassigned Area (0) is not a persisted row, so it is never guarded.
        self.assertNotIn(ResourceRef("area", "0", 7), baseline)
        self.assertEqual(
            baseline,
            tuple(
                sorted(
                    {
                        ResourceRef("takeoff", "30", 7),
                        ResourceRef("takeoff", "31", 7),
                        ResourceRef("takeoff", "32", 7),
                    }
                )
            ),
        )
        for missing in (
            ResourceRef("takeoff", "30", 7),
            ResourceRef("takeoff", "31", 7),
        ):
            with self.subTest(missing=missing):
                stale = _Harness()
                stale.tokens.guard = True
                stale.tokens.missing = {missing}
                with self.assertRaisesRegex(ValueError, "Refresh the Bid"):
                    submit(stale)
                self.assertEqual(stale.provider.requests, [])
        # Annotation properties carry no Takeoff baseline requirement.
        annotation = _Harness()
        annotation.tokens.guard = True
        annotation.tokens.missing = {ResourceRef("annotation", "rect/a1", 7)}
        annotation.service.queue_plan_properties(
            _Harness.DATABASE,
            "7",
            "annotation_text",
            [("a1", "rect", {"Text": "T"})],
            lambda _result: None,
        )
        self.assertEqual(len(annotation.provider.requests), 1)

    def test_property_ownership_must_belong_to_the_current_bid_and_database(self):
        for label, database, bid, takeoffs in (
            ("other bid", _Harness.DATABASE, "8", [("30", "5")]),
            ("other database", "C:/jobs/other.mdb", "7", [("30", "5")]),
            ("unknown takeoff", _Harness.DATABASE, "7", [("99", "5")]),
        ):
            with self.subTest(case=label):
                harness = _Harness()
                harness.tokens.guard = True
                with self.assertRaises(ValueError):
                    harness.service.queue_plan_properties(
                        database, bid, "takeoff_area", takeoffs, lambda _r: None
                    )
                self.assertEqual(harness.provider.requests, [])
                local = _Harness(sql=False)
                result = local.service.execute_plan_properties_local(
                    database, bid, "takeoff_area", takeoffs
                )
                self.assertEqual(
                    result.outcome_status, MutationOutcomeStatus.FAILED_BEFORE_COMMIT
                )
                self.assertEqual(local.calls, [])
                self.assertEqual(local.executor.requests, [])

    def test_unsupported_property_and_setting_kinds_are_rejected_before_queueing(self):
        harness = _Harness()
        harness.tokens.guard = True
        with self.assertRaisesRegex(ValueError, "Unsupported plan property"):
            harness.service.queue_plan_properties(
                _Harness.DATABASE, "7", "takeoff_color", [("30", 1)], lambda _r: None
            )
        with self.assertRaisesRegex(ValueError, "Unsupported page setting"):
            harness.service.queue_page_settings(
                _Harness.DATABASE, "7", "rotation", [["20", 1]], lambda _r: None
            )
        self.assertEqual(harness.provider.requests, [])

    def test_queued_plan_inputs_are_snapshotted_at_submission(self):
        harness = _Harness()
        takeoffs, annotations = ["30", "31"], [("a1", "rect")]
        harness.service.queue_plan_items_delete(
            _Harness.DATABASE, "7", takeoffs, annotations, lambda _r: None
        )
        positions = [("30", [1.0, 2.0])]
        harness.service.queue_plan_geometry(
            _Harness.DATABASE, "7", lambda _r: None, takeoff_positions=positions
        )
        takeoffs.clear()
        annotations.append(("a9", "line"))
        positions[0][1][0] = 99.0
        positions.clear()
        delete_request, delete_execute, _cb = harness.provider.requests[0]
        geometry_request, geometry_execute, _cb = harness.provider.requests[1]
        delete_execute()
        geometry_execute()
        self.assertEqual(
            harness.calls,
            [
                (
                    "delete_annotations",
                    "execute",
                    (_Harness.DATABASE, [("a1", "rect")]),
                    {},
                ),
                ("delete_takeoffs", "execute", (_Harness.DATABASE, ["30", "31"]), {}),
                (
                    "save_takeoff_positions",
                    "execute",
                    (_Harness.DATABASE, [("30", [1.0, 2.0])]),
                    {},
                ),
            ],
        )
        self.assertEqual(delete_request.payload.takeoff_uids, ("30", "31"))
        self.assertEqual(
            geometry_request.payload.takeoff_positions, (("30", (1.0, 2.0)),)
        )

    def test_queued_paste_validates_the_authoritative_identity_count(self):
        harness = _Harness()
        harness.service.queue_plan_items_paste(
            _Harness.DATABASE,
            MdbSqlBehaviorParityTests._mixed_paste_payload(),
            lambda _result: None,
        )
        validator = harness.provider.options[0]["result_validator"]
        complete = MutationExecutionResult(
            outcome_status=MutationOutcomeStatus.COMMITTED,
            created_resource_ids=("1", "2", "3", "4"),
        )
        self.assertEqual(validator(complete), "")
        self.assertEqual(
            validator(replace(complete, created_resource_ids=("1", "2", "3"))),
            "The paste returned an incomplete authoritative UID set.",
        )

    def test_page_setting_routing_wrapper_pins_the_queued_request(self):
        for kind, values, expected_family in (
            ("name", ["Sheet"], "pages"),
            ("show_mode", [2], "pages"),
        ):
            with self.subTest(kind=kind):
                harness = _Harness()
                completed = []
                self.assertIs(
                    harness.service.queue_page_setting_if_sql(
                        _Harness.DATABASE,
                        "20",
                        kind,
                        values,
                        owning_surface="rename-dialog",
                        callback=completed.append,
                    ),
                    True,
                )
                request, execute, callback = harness.provider.requests[0]
                self.assertEqual(request.bid_uid, 7)
                self.assertEqual(request.owning_surface, "rename-dialog")
                self.assertEqual(request.payload.setting_kind, kind)
                self.assertEqual(
                    json.loads(request.payload.updates_json), [["20", *values]]
                )
                self.assertEqual(
                    execute().authoritative_result.affected_families, (expected_family,)
                )
                failed = QueuedMutationResult(
                    database_id=_Harness.DATABASE,
                    runtime_generation=1,
                    operation_id=str(uuid.uuid4()),
                    outcome_status=MutationOutcomeStatus.REJECTED,
                    message="blocked",
                )
                with self.assertLogs(
                    "test.project_write_harness", level="WARNING"
                ) as logged:
                    callback(failed)
                self.assertIn("blocked", logged.output[0])
                self.assertEqual(completed, [failed])
        # Not routed: Access databases, inactive Bid, a foreign bulk-visibility Bid.
        access = _Harness(sql=False)
        self.assertIsNone(
            access.service.queue_page_setting_if_sql(
                _Harness.DATABASE, "20", "name", ["Sheet"]
            )
        )
        inactive = _Harness()
        inactive.data.bid_ref = None
        self.assertIs(
            inactive.service.queue_page_setting_if_sql(
                _Harness.DATABASE, "20", "name", ["Sheet"]
            ),
            False,
        )
        self.assertEqual(
            (access.provider.requests, inactive.provider.requests), ([], [])
        )
        with self.assertRaisesRegex(ValueError, "all-Layers visibility"):
            _Harness().service.queue_page_setting_if_sql(
                _Harness.DATABASE, "7", "all_layers_show", [True]
            )


class ProjectWriteImportContractTests(unittest.TestCase):
    def test_import_work_must_return_every_authoritative_identity_family(self):
        for label, value in (
            ("not a mapping", None),
            ("empty mapping", {}),
            (
                "missing takeoffs",
                {k: v for k, v in _import_work(None).items() if k != "takeoff_uids"},
            ),
            ("family is not a mapping", {**_import_work(None), "page_uids": ["20"]}),
        ):
            with self.subTest(case=label):
                harness = _Harness()
                harness.service.queue_project_import(
                    "database",
                    "9",
                    _import_payload(),
                    lambda _r: value,
                    lambda _r: None,
                )
                _request, execute, _callback = harness.provider.requests[0]
                with self.assertRaisesRegex(RuntimeError, "import"):
                    execute()


class ProjectWriteBranchContractTests(unittest.TestCase):
    """Result algebra, constructor wiring and branch-level contracts that the generic
    command tables cannot reach (each test names the mutants it exists for)."""

    def test_batch_result_flags_follow_requested_succeeded_failed_and_reload(self):
        for requested, succeeded, failed, reload_ok, expected in (
            ([], [], [], True, (False, False, False, False)),
            (["1"], [], [], True, (True, False, False, True)),
            (["1"], ["1"], [], True, (True, True, False, True)),
            (["1"], ["1"], [], False, (True, True, False, False)),
            (["1", "2"], ["1"], ["2"], True, (True, True, True, False)),
            (["1"], [], ["1"], True, (True, False, False, False)),
            (["1", "2"], ["1", "2"], [], True, (True, True, False, True)),
        ):
            with self.subTest(requested=requested, succeeded=succeeded, failed=failed):
                result = BatchWriteResult(
                    requested_uids=requested,
                    succeeded_uids=succeeded,
                    failed_uids=failed,
                    reload_success=reload_ok,
                )
                self.assertEqual(
                    (
                        bool(result.requested_uids),
                        result.any_success,
                        result.partial_success,
                        result.success,
                    ),
                    expected,
                )
                self.assertIs(bool(result), result.success)
        self.assertIs(BatchWriteResult().reload_success, True)
        self.assertEqual(
            (BatchWriteResult().requested_uids, BatchWriteResult().failed_uids),
            ([], []),
        )

    def test_constructor_requires_every_mutation_collaborator_and_all_annotation_use_cases(
        self,
    ):
        baseline = _Harness()
        arguments = dict(baseline.constructor_arguments)
        for name in (
            "bid_write_guard",
            "project_data_service",
            "mutation_executor",
            "session_registry",
            "concurrency_tokens",
            "sql_collaboration_provider",
        ):
            with self.subTest(missing=name), self.assertRaisesRegex(ValueError, name):
                ProjectWriteService(**{**arguments, name: None})
        for name in (
            "delete_annotations",
            "insert_annotations",
            "save_annotation_positions",
            "save_annotation_text_properties",
            "save_annotation_styles",
        ):
            with self.subTest(missing=name), self.assertRaisesRegex(
                ValueError, "annotation write use cases"
            ):
                ProjectWriteService(**{**arguments, name: None})
        ProjectWriteService(**arguments)

    def test_blocked_write_state_comes_from_the_connection_manager_only(self):
        harness = _Harness()
        service = harness.service
        self.assertIs(service._is_write_blocked(), False)
        service._connection_manager = SimpleNamespace(is_write_blocked=lambda: True)
        self.assertIs(service._is_write_blocked(), True)
        self.assertIs(
            service.save_page_view_state(_Harness.DATABASE, "20", 1, 2, 3), False
        )
        self.assertIs(
            service.save_bid_selected_page(_Harness.DATABASE, "7", "20"), False
        )
        self.assertIs(
            service.insert_default_layer_result(_Harness.DATABASE, "D", 1).success,
            False,
        )
        self.assertIs(
            service.update_all_default_layers_show(_Harness.DATABASE, True), False
        )
        self.assertEqual(harness.calls, [])
        self.assertIs(
            service.is_expected_deferred_write_blocked(_Harness.DATABASE), True
        )

    def _condition_family_harness(self, reader=None, replaced=True):
        harness = _Harness()
        reads = []

        def read(database, bid):
            reads.append((database, bid))
            if reader is not None:
                return reader(database, bid)
            return ({"10": Condition(uid="10"), "11": Condition(uid="11")}, {})

        harness.service._condition_family_reader = read
        replacements = []

        def replace_family(bid_ref, conditions, folders):
            replacements.append((bid_ref, sorted(conditions), sorted(folders)))
            return replaced

        harness.data.replace_condition_family = replace_family
        return harness, reads, replacements

    def test_condition_family_refresh_projects_in_place_only_for_family_only_changes(
        self,
    ):
        database, bid_ref = _Harness.DATABASE, BidRef(_Harness.DATABASE, "7")
        for label, fields, operations, in_place in (
            ("update", ["name"], [ChangeOperation.UPDATE], True),
            ("reorder", ["ref_no"], [ChangeOperation.REORDER], True),
            (
                "update and reorder",
                [],
                [ChangeOperation.UPDATE, ChangeOperation.REORDER],
                True,
            ),
            ("folder-only", ["condition_folder"], [], True),
            ("create", [], [ChangeOperation.CREATE], False),
            ("delete", [], [ChangeOperation.DELETE], False),
            (
                "update and delete",
                [],
                [ChangeOperation.UPDATE, ChangeOperation.DELETE],
                False,
            ),
            ("no operation and other field", ["name"], [], False),
            ("nothing", [], [], False),
            ("folder-only with other field", ["condition_folder", "name"], [], False),
        ):
            with self.subTest(case=label):
                harness, reads, replacements = self._condition_family_harness()
                projected = []
                result = harness.service.reload_conditions_and_notify(
                    database,
                    "7",
                    ["10", "", "10"],
                    fields,
                    operations,
                    on_projected=lambda: projected.append("projected"),
                )
                self.assertIs(result, True)
                self.assertEqual(reads, [(database, "7")] if in_place else [])
                self.assertEqual(
                    replacements,
                    [(bid_ref, ["10", "11"], [])] if in_place else [],
                )
                self.assertEqual(harness.reloads, [] if in_place else [database])
                self.assertEqual(projected, ["projected"])
                self.assertEqual(
                    [event.__name__ for event, _payload in harness.events.published],
                    ["ConditionsChangedEvent"],
                )
                payload = harness.events.published[0][1]
                self.assertEqual(payload["condition_uids"], ["10"])
                self.assertEqual(payload["changed_fields"], sorted(fields))
                self.assertEqual(
                    payload["change_operations"],
                    sorted(op.value for op in set(operations)),
                )
                self.assertIs(payload["invalidates_undo"], False)
                self.assertIs(payload["local_completion"], True)

    def test_condition_family_refresh_falls_back_to_a_full_reload_when_it_cannot_project(
        self,
    ):
        database = _Harness.DATABASE

        def missing_condition(_database, _bid):
            return ({"10": Condition(uid="10")}, {})

        refreshed = (
            "DatabaseRefreshedEvent",
            {"file_path": database, "external_change": True},
        )
        for label, setup, expected_last in (
            ("replacement refused", {"replaced": False}, "refreshed"),
            (
                "a Takeoff references a missing Condition",
                {"reader": missing_condition},
                "refreshed",
            ),
            ("the Bid owner changed while reading", {"swap_owner": True}, "refreshed"),
            ("another Bid is active", {"active": BidRef(database, "9")}, "conditions"),
        ):
            with self.subTest(case=label):
                harness, _reads, _replacements = self._condition_family_harness(
                    reader=setup.get("reader"), replaced=setup.get("replaced", True)
                )
                if "active" in setup:
                    harness.data.bid_ref = setup["active"]
                if setup.get("swap_owner"):
                    reader = harness.service._condition_family_reader

                    def read_then_replace_owner(database_id, bid_uid):
                        harness.data.bid = SimpleNamespace(uid="7")
                        return reader(database_id, bid_uid)

                    harness.service._condition_family_reader = read_then_replace_owner
                harness.data.takeoffs = [
                    Takeoff(uid="30", page_uid="20", condition_uid="11")
                ]
                projected = []
                self.assertIs(
                    harness.service.reload_conditions_and_notify(
                        database,
                        "7",
                        ["10"],
                        ["name"],
                        [ChangeOperation.UPDATE],
                        on_projected=lambda: projected.append("projected"),
                    ),
                    True,
                )
                self.assertEqual(harness.reloads, [database])
                self.assertEqual(projected, ["projected"])
                event, payload = harness.events.published[-1]
                if expected_last == "refreshed":
                    self.assertEqual((event.__name__, dict(payload)), refreshed)
                else:
                    self.assertEqual(event.__name__, "ConditionsChangedEvent")

    def test_condition_family_refresh_failures_return_false_without_events(self):
        database = _Harness.DATABASE
        # reader raising: logged with its traceback, no reload, no event, no callback
        harness, reads, _replacements = self._condition_family_harness(
            reader=lambda _d, _b: (_ for _ in ()).throw(OSError("read failed"))
        )
        projected = []
        with self.assertLogs("test.project_write_harness", level="WARNING") as logged:
            self.assertIs(
                harness.service.reload_conditions_and_notify(
                    database,
                    "7",
                    ["10"],
                    ["name"],
                    [ChangeOperation.UPDATE],
                    on_projected=lambda: projected.append(1),
                ),
                False,
            )
        self.assertIn("Condition-family refresh failed", logged.output[0])
        self.assertEqual(logged.records[0].exc_info[0], OSError)
        self.assertEqual(
            (harness.reloads, harness.events.published, projected), ([], [], [])
        )
        # fallback reload failing (family path) and ordinary reload failing
        for operations, fields in (
            ([ChangeOperation.UPDATE], ["name"]),
            ([ChangeOperation.CREATE], []),
        ):
            with self.subTest(operations=operations):
                harness = _Harness(reload_result=False)
                harness.data.replace_condition_family = lambda *_a: False
                projected = []
                self.assertIs(
                    harness.service.reload_conditions_and_notify(
                        database,
                        "7",
                        ["10"],
                        fields,
                        operations,
                        on_projected=lambda: projected.append(1),
                    ),
                    False,
                )
                self.assertEqual(
                    (harness.reloads, harness.events.published, projected),
                    ([database], [], []),
                )

    def _created_condition_harness(self):
        harness = _Harness({"insert_condition": "c9"})
        previous = SimpleNamespace(uid="7", name="before")
        harness.data.bid = previous
        condition = Condition(uid="c9", name="C")
        folder = BidConditionFolder(uid="f1", name="Walls")
        harness.data.get_bid_conditions = lambda: {"c9": condition}
        harness.data.get_bid_condition_folders = lambda: {"f1": folder}
        return harness, previous, condition, folder

    def test_created_condition_projection_requires_the_same_current_bid_before_and_after(
        self,
    ):
        database = _Harness.DATABASE
        spec = CreateConditionSpec(name="C", folder_uid="f1")
        harness, previous, condition, folder = self._created_condition_harness()
        reloaded = SimpleNamespace(uid="7", name="after")
        harness.service._reload_database = lambda path: (
            harness.reloads.append(path)
            or setattr(harness.data, "bid", reloaded)
            or True
        )
        projection = harness.service.create_condition_result(
            database, "7", spec
        ).projection
        self.assertEqual(
            (
                projection.previous_bid,
                projection.bid,
                projection.condition,
                projection.folder,
            ),
            (previous, reloaded, condition, folder),
        )
        # no folder requested: the projection carries no folder
        harness, _previous, condition, _folder = self._created_condition_harness()
        result = harness.service.create_condition_result(
            database, "7", CreateConditionSpec(name="C")
        )
        self.assertIsNone(result.projection.folder)
        self.assertIs(result.projection.condition, condition)

        def unload_bid(harness):
            harness.data.bid = None

        def replace_bid_during_write(harness):
            def write(*_args):
                harness.data.bid = SimpleNamespace(uid="7", name="swapped")
                return "c9"

            harness.service._insert_condition = SimpleNamespace(execute=write)

        def other_bid_current(harness):
            harness.data.bid_ref = BidRef(database, "9")

        def condition_missing(harness):
            harness.data.get_bid_conditions = lambda: {}

        def folder_missing(harness):
            harness.data.get_bid_condition_folders = lambda: {}

        def bid_missing_after_reload(harness):
            harness.service._reload_database = lambda path: (
                harness.reloads.append(path)
                or setattr(harness.data, "bid", None)
                or True
            )

        for label, change in (
            ("Bid was not loaded", unload_bid),
            ("Bid replaced by the write itself", replace_bid_during_write),
            ("another Bid became current", other_bid_current),
            ("condition missing after reload", condition_missing),
            ("folder missing after reload", folder_missing),
            ("Bid missing after reload", bid_missing_after_reload),
        ):
            with self.subTest(case=label):
                harness, *_ = self._created_condition_harness()
                change(harness)
                result = harness.service.create_condition_result(database, "7", spec)
                self.assertIsNone(result.projection)
                self.assertEqual(result.value, "c9")
                self.assertIs(result.write_success, True)

    def test_update_condition_reports_each_failure_distinctly(self):
        database = _Harness.DATABASE

        def update(results=None, **kwargs):
            harness = _Harness(
                results or {"update_condition": UpdateConditionResultDto(success=True)},
                **kwargs,
            )
            harness.data.get_bid_conditions = lambda: {
                "c1": Condition(uid="c1", name="N")
            }
            result = harness.service.update_condition(
                database, "7", "c1", UpdateConditionDto({"name": "N"})
            )
            return harness, result

        harness = None
        harness, result = update()
        self.assertIs(result.success, True)
        self.assertEqual(
            [r[:2] for r in harness.executor.recorder.changes],
            [(ResourceRef("condition", "c1", 7), ChangeOperation.UPDATE)],
        )
        self.assertEqual(harness.executor.recorder.changes[0][2], ("name",))
        # writer reports failure: nothing recorded, error text from the writer
        harness, result = update(
            {
                "update_condition": UpdateConditionResultDto(
                    success=False, error="rejected"
                )
            }
        )
        self.assertEqual((result.success, result.error), (False, "rejected"))
        self.assertEqual((harness.executor.recorder.changes, harness.reloads), ([], []))
        # reload failing after a good write replaces the result with the refresh error
        harness, result = update(reload_result=False)
        self.assertEqual(
            (result.success, result.error),
            (False, "Database reload failed after saving condition"),
        )
        self.assertEqual(len(harness.executor.recorder.changes), 1)
        # non-committed outcomes (with the real executor contract: no value)
        for status in (
            MutationOutcomeStatus.REJECTED,
            MutationOutcomeStatus.FAILED_BEFORE_COMMIT,
            MutationOutcomeStatus.COMMIT_STATUS_UNKNOWN,
            MutationOutcomeStatus.CONFLICT,
        ):
            with self.subTest(status=status):
                harness = _Harness(
                    {"update_condition": UpdateConditionResultDto(success=True)}
                )
                harness.executor.status = status
                if status == MutationOutcomeStatus.CONFLICT:
                    harness.executor.conflict = _synchronization_conflict()
                result = harness.service.update_condition(
                    database, "7", "c1", UpdateConditionDto({"name": "N"})
                )
                self.assertEqual(
                    (result.success, result.error),
                    (
                        False,
                        (
                            "stale"
                            if status == MutationOutcomeStatus.CONFLICT
                            else "The condition update could not be completed"
                        ),
                    ),
                )
                self.assertEqual(harness.reloads, [])
                # an uncertain commit has run the operation (the caller must not
                # assume nothing happened); every other non-committed status has not
                self.assertEqual(
                    [call[0] for call in harness.calls],
                    (
                        ["update_condition"]
                        if status == MutationOutcomeStatus.COMMIT_STATUS_UNKNOWN
                        else []
                    ),
                )
        # database refresh may be delegated to the caller
        harness = _Harness({"update_condition": UpdateConditionResultDto(success=True)})
        result = harness.service.update_condition(
            database, "7", "c1", UpdateConditionDto({"name": "N"}), False
        )
        self.assertIs(result.success, True)
        self.assertEqual((harness.reloads, harness.events.published), ([], []))

    def test_changed_fields_of_a_condition_update_add_elevation_fields_only_on_a_new_signature(
        self,
    ):
        harness = _Harness()
        harness.data.get_bid_conditions = lambda: {
            "c1": Condition(uid="c1", name="Walls @T 10' - 0\""),
            "c2": Condition(uid="c2", name="Slab @T 10' - 0\""),
        }
        service = harness.service
        for uids, changes, expected in (
            (["c1"], {"name": "Renamed @T 10' - 0\""}, ("name",)),
            (["c1"], {"name": "Renamed @B 8' - 0\""}, ("is_top", "name", "z_value")),
            (["c1", "c2"], {"name": "Both @T 10' - 0\""}, ("name",)),
            (
                ["c1", "missing"],
                {"name": "Both @T 10' - 0\""},
                ("is_top", "name", "z_value"),
            ),
            (["c1"], {"name": "X @B 8' - 0\"", "z_value": 1.0}, ("name", "z_value")),
            (["c1"], {"name": "X @B 8' - 0\"", "is_top": True}, ("is_top", "name")),
            (["c1"], {"notes": "n"}, ("notes",)),
            (["c1"], {"notes": "n", "layer_uid": "40"}, ("layer_uid", "notes")),
        ):
            with self.subTest(uids=uids, changes=changes):
                self.assertEqual(
                    service._condition_update_changed_fields(uids, changes), expected
                )

    def test_queued_catalog_saves_reject_empty_changes_and_incomplete_identity_maps(
        self,
    ):
        queues = (
            ("condition_types", "queue_condition_types_save", "save_condition_types"),
            ("job_statuses", "queue_job_statuses_save", "save_job_statuses"),
            ("employees", "queue_employees_save", "save_employees"),
            ("pay_classes", "queue_pay_classes_save", "save_pay_classes"),
        )
        for family, queue_name, use_case in queues:
            for label, changes in (
                ("none", None),
                ("empty", {}),
                ("blank sections", {"new": [], "updated": [], "deleted_uids": []}),
                ("only blank deletions", {"deleted_uids": ["", ""]}),
            ):
                with self.subTest(family=family, changes=label):
                    harness = _Harness()
                    with self.assertRaisesRegex(ValueError, "requires"):
                        getattr(harness.service, queue_name)(
                            "database", changes, lambda _r: None
                        )
                    self.assertEqual(harness.provider.requests, [])
            for failure in (None, False, {}):
                with self.subTest(family=family, writer_result=failure):
                    harness = _Harness({use_case: failure})
                    getattr(harness.service, queue_name)(
                        "database",
                        {"new": [{"uid": "n", "name": "N"}]},
                        lambda _r: None,
                    )
                    _request, execute, _callback = harness.provider.requests[0]
                    with self.assertRaisesRegex(RuntimeError, "incomplete"):
                        execute()
                    self.assertEqual(harness.executor.recorder.changes, [])
        for failure in (None, False):
            harness = _Harness({"save_bid_areas": failure})
            harness.service.queue_bid_areas_save(
                "database", "7", _area_changes(), lambda _r: None
            )
            with self.assertRaisesRegex(RuntimeError, "incomplete"):
                harness.provider.requests[0][1]()

    def test_queued_condition_type_save_blocks_deleting_types_still_in_use(self):
        harness = _Harness({"save_condition_types": {}})
        harness.service.queue_condition_types_save(
            "database", {"deleted_uids": ["used"]}, lambda _r: None
        )
        _request, execute, _callback = harness.provider.requests[0]
        with self.assertRaisesRegex(RuntimeError, "still referenced"):
            execute()
        self.assertEqual(harness.calls, [])
        harness.service._condition_type_uids_in_use_provider = None
        with self.assertRaisesRegex(RuntimeError, "still referenced"):
            execute()
        self.assertEqual(harness.calls, [])

    def test_queued_annotation_property_updates_ignore_malformed_entries_when_building_resources(
        self,
    ):
        updates = [
            ("a1", "rect", {"Text": "T"}),
            ("", "rect", {}),
            ("a2", "", {}),
            ("a3",),
            (),
        ]
        queued = _Harness()
        queued.tokens.guard = True
        queued.service.queue_plan_properties(
            _Harness.DATABASE, "7", "annotation_text", updates, lambda _r: None
        )
        self.assertEqual(
            queued.provider.requests[0][0].resources,
            (ResourceRef("annotation", "rect/a1", 7),),
        )

    def test_all_layers_visibility_routing_validates_its_arguments(self):
        for label, values, error in (
            ("one value", [True], "all-Layers visibility"),
            ("three values", [True, ["40"], 3], "all-Layers visibility"),
            ("uids not a sequence", [True, "40"], "all-Layers visibility"),
        ):
            with self.subTest(case=label):
                harness = _Harness()
                with self.assertRaisesRegex(ValueError, error):
                    harness.service.queue_page_setting_if_sql(
                        _Harness.DATABASE, "7", "all_layers_show", values
                    )
                self.assertEqual(harness.provider.requests, [])
        harness = _Harness()
        completed = []
        self.assertIs(
            harness.service.queue_page_setting_if_sql(
                _Harness.DATABASE,
                "7",
                "all_layers_show",
                [0, ("40", 41)],
                owning_surface="layers-panel",
                callback=completed.append,
            ),
            True,
        )
        request = harness.provider.requests[0][0]
        self.assertEqual(
            (request.owning_surface, request.resources, request.payload.write_kind),
            (
                "layers-panel",
                (ResourceRef("layers_collection", "7", 7),),
                "update_all_layers_show",
            ),
        )
        self.assertEqual(
            json.loads(request.payload.values_json),
            {"layer_uids": ["40", "41"], "show": False},
        )
        # the page uid of the routed call must be the active Bid for bulk visibility
        self.assertIs(
            harness.service.queue_page_setting_if_sql(
                _Harness.DATABASE, "8", "all_layers_show", [True, ["40"]]
            ),
            False,
        )
        self.assertEqual(len(harness.provider.requests), 1)
        # a rejected queue admission is reported as not queued
        harness.provider.queue_request = lambda *_a, **_k: -1
        self.assertIs(
            harness.service.queue_page_setting_if_sql(
                _Harness.DATABASE, "20", "name", ["Sheet"]
            ),
            False,
        )

    def test_failed_or_unlisted_page_setting_completion_is_logged_by_state(self):
        harness = _Harness()
        completed = []
        harness.service.queue_page_setting_if_sql(
            _Harness.DATABASE, "20", "name", ["Sheet"], callback=completed.append
        )
        _request, _execute, callback = harness.provider.requests[0]
        for status, logged in (
            (MutationOutcomeStatus.COMMITTED, False),
            (MutationOutcomeStatus.COMMIT_STATUS_UNKNOWN, False),
            (MutationOutcomeStatus.COMMITTED_PROJECTION_FAILED, False),
            (MutationOutcomeStatus.REJECTED, True),
            (MutationOutcomeStatus.FAILED_BEFORE_COMMIT, True),
            (MutationOutcomeStatus.CONFLICT, True),
        ):
            with self.subTest(status=status):
                result = QueuedMutationResult(
                    database_id=_Harness.DATABASE,
                    runtime_generation=1,
                    operation_id=str(uuid.uuid4()),
                    outcome_status=status,
                    message="why",
                )
                if logged:
                    with self.assertLogs(
                        "test.project_write_harness", level="WARNING"
                    ) as out:
                        callback(result)
                    self.assertIn("why", out.output[0])
                    self.assertIn("20", out.output[0])
                else:
                    with self.assertNoLogs(
                        "test.project_write_harness", level="WARNING"
                    ):
                        callback(result)
                self.assertIs(completed[-1], result)


class ProjectWriteExecutorContractTests(unittest.TestCase):
    """A mutation that did not commit is never reported as a success, whatever the
    executor hands back. DatabaseMutationResult itself refuses a value for a
    non-committed outcome (decision D4), so the leaking executor below forges one
    past the DTO: a defence-in-depth probe that every command, including the seven
    that used to read only `.value`, checks the outcome itself."""

    NON_COMMITTED = (
        MutationOutcomeStatus.REJECTED,
        MutationOutcomeStatus.FAILED_BEFORE_COMMIT,
        MutationOutcomeStatus.CONFLICT,
        MutationOutcomeStatus.COMMIT_STATUS_UNKNOWN,
    )

    @staticmethod
    def _leaking(harness, status):
        executor = harness.executor

        def execute(request, operation):
            executor.calls += 1
            executor.requests.append(request)
            value = operation(executor.recorder)
            executor.values.append(value)
            result = DatabaseMutationResult(
                operation_id=request.operation_id,
                outcome_status=status,
                conflict=executor.conflict,
                resulting_versions=executor.resulting_versions,
                commit_attempted=False,
                consumed_lock_tokens=(),
            )
            object.__setattr__(result, "value", value)
            return result

        executor.execute = execute

    def _local(self, rows, label, status, leak):
        results, command = next(
            (row[1], row[2]) for row in rows(_Harness.DATABASE) if row[0] == label
        )
        harness = _Harness(results)
        if status == MutationOutcomeStatus.CONFLICT:
            harness.executor.conflict = _synchronization_conflict()
        if leak:
            self._leaking(harness, status)
        else:
            harness.executor.status = status
        try:
            result = command(harness.service)
        except Exception as exc:  # pinned by the scenario goldens
            result = f"raised {type(exc).__name__}: {exc}"
        return (
            _outcome_text(result),
            harness.reloads,
            [event.__name__ for event, _payload in harness.events.published],
        )

    def _queued(self, rows, label, status, leak):
        row = next(row for row in rows() if row[0] == label)
        results, submit = row[1], row[2]
        harness = _Harness(results)
        if len(row) > 3 and row[3]:
            row[3](harness)
        submit(harness.service, lambda _result: None)
        _request, execute, _callback = harness.provider.requests[-1]
        if status == MutationOutcomeStatus.CONFLICT:
            harness.executor.conflict = _synchronization_conflict()
        if leak:
            self._leaking(harness, status)
        else:
            harness.executor.status = status
        try:
            return _outcome_text(execute())
        except Exception as exc:  # pinned by the scenario goldens
            return f"raised {type(exc).__name__}: {exc}"

    def test_local_commands_ignore_the_value_of_a_mutation_that_did_not_commit(self):
        checked = 0
        for rows in (_local_rows, _plan_local_rows):
            for row in rows():
                for status in self.NON_COMMITTED:
                    with self.subTest(command=row[0], status=status.value):
                        self.assertEqual(
                            self._local(rows, row[0], status, leak=True),
                            self._local(rows, row[0], status, leak=False),
                        )
                    checked += 1
        rows = len(_local_rows()) + len(_plan_local_rows())
        self.assertEqual(checked, len(self.NON_COMMITTED) * rows)

    def test_condition_folder_delete_reports_strict_booleans_when_not_committed(self):
        # Decision D4(c): a non-committed outcome yields False (never None) from the
        # folder delete, like every sibling command, and no reload or event follows.
        for status in self.NON_COMMITTED:
            for leak in (False, True):
                with self.subTest(status=status.value, leak=leak):
                    harness = _Harness({})
                    if status == MutationOutcomeStatus.CONFLICT:
                        harness.executor.conflict = _synchronization_conflict()
                    if leak:
                        self._leaking(harness, status)
                    else:
                        harness.executor.status = status
                    detailed = harness.service.delete_condition_folders_result(
                        _Harness.DATABASE, "7", ["f1", "f2"]
                    )
                    self.assertIs(detailed.write_success, False)
                    self.assertIs(detailed.reload_success, False)
                    self.assertIs(detailed.success, False)
                    self.assertEqual(
                        (harness.reloads, detailed.failure_reason), ([], None)
                    )
                    harness = _Harness({})
                    if status == MutationOutcomeStatus.CONFLICT:
                        harness.executor.conflict = _synchronization_conflict()
                    if leak:
                        self._leaking(harness, status)
                    else:
                        harness.executor.status = status
                    self.assertIs(
                        harness.service.delete_condition_folders(
                            _Harness.DATABASE, ["f1"]
                        ),
                        False,
                    )
                    self.assertEqual(harness.reloads, [])

    def test_unavailable_editing_reports_strict_booleans_for_the_folder_delete(self):
        harness = _Harness({}, editable=False)
        detailed = harness.service.delete_condition_folders_result(
            _Harness.DATABASE, "7", ["f1"]
        )
        self.assertIs(detailed.write_success, False)
        self.assertIs(
            harness.service.delete_condition_folders(_Harness.DATABASE, ["f1"]), False
        )
        self.assertEqual((harness.executor.calls, harness.reloads), (0, []))

    def test_queued_commands_ignore_the_value_of_a_mutation_that_did_not_commit(self):
        checked = 0
        for rows in (_queue_rows, _plan_queue_rows):
            for row in rows():
                for status in self.NON_COMMITTED:
                    with self.subTest(command=row[0], status=status.value):
                        self.assertEqual(
                            self._queued(rows, row[0], status, leak=True),
                            self._queued(rows, row[0], status, leak=False),
                        )
                    checked += 1
        rows = len(_queue_rows()) + len(_plan_queue_rows())
        self.assertEqual(checked, len(self.NON_COMMITTED) * rows)


class ActiveBidGuardCompositePlanCommandTests(unittest.TestCase):
    """Decision D8: the composite Access plan commands (delete, geometry, properties,
    paste) consult ActiveBidWriteGuard exactly like their legacy single-purpose
    equivalents. The queued SQL commands (queue_plan_* / queue_page_settings) are
    SQL-only entry points (their callers branch on uses_sql_collaboration_mutations
    and fall back to the guarded legacy commands for Access); decision D8 left them
    unchanged, decisions H3 and P2 later made them refuse a locked active Bid at queue
    time (see LayerAreaLockedBidParityTests and PageSettingPlanLockedBidParityTests)."""

    LEGACY_EQUIVALENTS = {
        "delete_local": "delete_takeoffs",
        "geometry_local": "save_takeoff_positions",
        "paste_local": "insert_takeoffs_result without refresh",
    }

    @staticmethod
    def _row(rows, label):
        return next(row for row in rows() if row[0] == label)

    def _run(self, rows, label, *, locked, database=_Harness.DATABASE):
        row = next(row for row in rows(database) if row[0] == label)
        harness = _Harness(row[1], sql=False)
        harness.data.locked = locked
        return harness, row[2](harness.service)

    def test_locked_active_bid_rejects_every_composite_plan_command_untouched(self):
        for row in _plan_local_rows():
            label = row[0]
            with self.subTest(command=label):
                # Positive control: the very same command commits when not locked.
                control, committed = self._run(_plan_local_rows, label, locked=False)
                self.assertEqual(
                    committed.outcome_status, MutationOutcomeStatus.COMMITTED
                )
                self.assertGreater(control.executor.calls, 0)
                harness, result = self._run(_plan_local_rows, label, locked=True)
                self.assertEqual(result.outcome_status, MutationOutcomeStatus.REJECTED)
                self.assertTrue(result.message)
                self.assertIs(result.commit_attempted, False)
                self.assertIsNone(result.authoritative_result)
                self.assertEqual(
                    (
                        harness.executor.calls,
                        harness.calls,
                        harness.reloads,
                        harness.events.published,
                    ),
                    (0, [], [], []),
                )

    def test_a_locked_active_bid_of_another_database_does_not_block_plan_commands(self):
        other = _ALTERNATE_DATABASES["other_database"]
        executed = 0
        for row in _plan_local_rows(other):
            with self.subTest(command=row[0]):
                control, expected = self._run(
                    _plan_local_rows, row[0], locked=False, database=other
                )
                harness, result = self._run(
                    _plan_local_rows, row[0], locked=True, database=other
                )
                self.assertNotEqual(
                    result.outcome_status, MutationOutcomeStatus.REJECTED
                )
                self.assertEqual(result.outcome_status, expected.outcome_status)
                self.assertEqual(harness.executor.calls, control.executor.calls)
                executed += harness.executor.calls
        # Positive control: the unlocked-equivalent commands do reach the executor.
        self.assertGreater(executed, 0)

    def test_composite_and_legacy_commands_reject_a_locked_bid_side_by_side(self):
        for plan_prefix, legacy_label in self.LEGACY_EQUIVALENTS.items():
            plan_label = next(
                row[0] for row in _plan_local_rows() if row[0].startswith(plan_prefix)
            )
            with self.subTest(plan=plan_label, legacy=legacy_label):
                legacy_harness, legacy = self._run(
                    _local_rows, legacy_label, locked=True
                )
                plan_harness, plan = self._run(
                    _plan_local_rows, plan_label, locked=True
                )
                self.assertFalse(legacy)
                self.assertEqual(plan.outcome_status, MutationOutcomeStatus.REJECTED)
                self.assertEqual(legacy_harness.executor.calls, 0)
                self.assertEqual(plan_harness.executor.calls, 0)
                self.assertEqual(legacy_harness.calls, plan_harness.calls)

    def test_paste_into_an_unlocked_destination_bid_is_not_blocked(self):
        # The guard is per Bid: the locked active Bid 7 only blocks writes whose
        # destination is Bid 7.
        harness = _Harness(
            {
                "insert_takeoffs": _Seq(["p-new"], ["h-new"]),
                "insert_annotations": _Seq(["named-new"], ["rect-new"]),
                ("duplicate_conditions", "execute_to_bid"): {"c1": "c9"},
            },
            sql=False,
        )
        harness.data.locked = True
        payload = replace(_cross_bid_paste_payload(), destination_bid_uid="8")
        result = harness.service.execute_plan_items_paste_local(
            _Harness.DATABASE, payload
        )
        self.assertEqual(result.outcome_status, MutationOutcomeStatus.COMMITTED)
        self.assertGreater(harness.executor.calls, 0)


class ConditionFolderLockedBidParityTests(unittest.TestCase):
    """Decisions F2 and G3: every Condition command (create, update of any field, move,
    rename, delete, duplicate and paste-duplicate, renumber, and the folder commands)
    is blocked on a status-locked ACTIVE Bid on both backends, exactly like the Access
    commands (the guard is evaluated at the service entry point; no write, no reload,
    no event). Access reports the block through its result type; the SQL queue_* entry
    points have no result to return, so they raise ActiveBidLockedError at submission
    (nothing queued, callback never invoked, no event) and the handler logs it like the
    Access failure. The table is operation x backend x situation {locked active Bid,
    unlocked control, locked Bid of another database, other Bid of the same database};
    the Condition-type catalog commands are the pinned exception (never blocked on
    either backend). The write service is the only gate for folder edits, as for
    Access: UIAccessManager does not lock-block EDIT_CONDITION_STRUCTURE on either
    backend."""

    OTHER = _ALTERNATE_DATABASES["other_database"]
    MOVE = UpdateConditionDto({"folder_uid": "f1"})

    @staticmethod
    def _summary(result):
        if isinstance(result, WriteReloadResult):
            return (result.value, result.write_success, result.reload_success)
        if isinstance(result, UpdateConditionResultDto):
            return (result.success, result.error)
        return result

    # (name, scripted results, access(service, database, bid), access allowed,
    # access blocked, sql(service, database, bid, callback)); access is None where the
    # Access command takes no Bid (rename resolves the active Bid itself).
    def _operations(self):
        blocked_result = (None, False, False)
        return (
            (
                "create folder",
                {"insert_condition_folder": "f9"},
                lambda s, d, b: s.create_condition_folder_result(d, b, "Walls", "f1"),
                ("f9", True, True),
                blocked_result,
                lambda s, d, b, cb: s.queue_condition_folder_create(
                    d, b, "Walls", "f1", cb
                ),
            ),
            (
                "create root folder",
                {"insert_condition_folder": "f9"},
                lambda s, d, b: s.create_condition_folder_result(d, b, "Walls", None),
                ("f9", True, True),
                blocked_result,
                lambda s, d, b, cb: s.queue_condition_folder_create(
                    d, b, "Walls", None, cb
                ),
            ),
            (
                "rename folder",
                {},
                None,
                True,
                False,
                lambda s, d, b, cb: s.queue_condition_folder_rename(
                    d, b, "f1", "N", cb
                ),
            ),
            (
                "delete folders",
                {},
                lambda s, d, b: s.delete_condition_folders_result(d, b, ["f1", "f2"]),
                (["f1", "f2"], True, True),
                blocked_result,
                lambda s, d, b, cb: s.queue_condition_folders_delete(
                    d, b, ["f1", "f2"], cb
                ),
            ),
            (
                "move condition to folder",
                {"update_condition": UpdateConditionResultDto(success=True)},
                lambda s, d, b: s.update_condition(d, b, "c1", self.MOVE),
                (True, None),
                (False, "The active bid is locked"),
                lambda s, d, b, cb: s.queue_conditions_update(
                    d, b, ["c1", "c2"], {"folder_uid": "f1"}, cb
                ),
            ),
            (
                "move condition to the root",
                {"update_condition": UpdateConditionResultDto(success=True)},
                lambda s, d, b: s.update_condition(
                    d, b, "c1", UpdateConditionDto({"folder_uid": None})
                ),
                (True, None),
                (False, "The active bid is locked"),
                lambda s, d, b, cb: s.queue_conditions_update(
                    d, b, ["c1"], {"folder_uid": None}, cb
                ),
            ),
            (
                "cut-paste move into a folder and type",
                {"update_condition": UpdateConditionResultDto(success=True)},
                lambda s, d, b: s.update_condition(
                    d,
                    b,
                    "c1",
                    UpdateConditionDto({"folder_uid": "f1", "cdn_type_uid": "3"}),
                ),
                (True, None),
                (False, "The active bid is locked"),
                lambda s, d, b, cb: s.queue_conditions_update(
                    d,
                    b,
                    ["c1"],
                    {"folder_uid": "f1", "cdn_type_uid": "3"},
                    cb,
                ),
            ),
        ) + self._condition_operations()

    # Decision G3: the same table for every other Condition command. Each Access twin
    # consults the guard unconditionally (whatever the Condition, folder or fields), so
    # the SQL queue entry point must too.
    def _condition_operations(self):
        update_blocked = (False, "The active bid is locked")
        update_script = {"update_condition": UpdateConditionResultDto(success=True)}

        def update_row(name, changes):
            return (
                name,
                update_script,
                lambda s, d, b: s.update_condition(
                    d, b, "c1", UpdateConditionDto(dict(changes))
                ),
                (True, None),
                update_blocked,
                lambda s, d, b, cb: s.queue_conditions_update(
                    d, b, ["c1", "c2"], dict(changes), cb
                ),
            )

        def create_row(name, spec):
            return (
                name,
                {"insert_condition": "c9"},
                lambda s, d, b: s.create_condition_result(d, b, spec),
                ("c9", True, True),
                (None, False, False),
                lambda s, d, b, cb: s.queue_condition_create(d, b, spec, cb),
            )

        duplicate_script = {
            "duplicate_conditions": ["c9"],
            "update_condition": UpdateConditionResultDto(success=True),
        }
        return (
            create_row("create condition", CreateConditionSpec(name="C")),
            create_row(
                "create condition in a folder",
                CreateConditionSpec(name="C", folder_uid="f1"),
            ),
            create_row(
                "create condition with type and layer",
                CreateConditionSpec(name="C", cdn_type_uid="3", layer_uid="40"),
            ),
            update_row("rename condition", {"name": "N"}),
            update_row("clear condition type", {"cdn_type_uid": None}),
            update_row("set condition type", {"cdn_type_uid": "3"}),
            update_row("set condition layer", {"layer_uid": "40"}),
            update_row("change a condition field", {"notes": "x"}),
            (
                "delete conditions",
                {},
                lambda s, d, b: s.delete_conditions(d, b, ["c1", "c2"]),
                True,
                False,
                lambda s, d, b, cb: s.queue_conditions_delete(d, b, ["c1", "c2"], cb),
            ),
            (
                "duplicate conditions",
                duplicate_script,
                lambda s, d, b: s.duplicate_conditions_result(d, b, ["c1"]),
                (["c9"], True, True),
                ([], False, False),
                lambda s, d, b, cb: s.queue_conditions_duplicate(d, b, ["c1"], cb),
            ),
            (
                "paste-duplicate conditions into a folder",
                duplicate_script,
                lambda s, d, b: s.duplicate_conditions_result(d, b, ["c1"]),
                (["c9"], True, True),
                ([], False, False),
                lambda s, d, b, cb: s.queue_conditions_duplicate(
                    d, b, ["c1"], cb, target_changes={"folder_uid": "f1"}
                ),
            ),
            (
                "paste-duplicate conditions into a type",
                duplicate_script,
                lambda s, d, b: s.duplicate_conditions_result(d, b, ["c1"]),
                (["c9"], True, True),
                ([], False, False),
                lambda s, d, b, cb: s.queue_conditions_duplicate(
                    d,
                    b,
                    ["c1"],
                    cb,
                    target_changes={"folder_uid": None, "cdn_type_uid": "3"},
                ),
            ),
            (
                "renumber conditions",
                {},
                lambda s, d, b: s.renumber_conditions(d, b, ["c2", "c1"]),
                True,
                False,
                lambda s, d, b, cb: s.queue_conditions_renumber(d, b, ["c2", "c1"], cb),
            ),
        )

    def _access(self, operation, *, locked, database=_Harness.DATABASE, bid="7"):
        harness = _Harness(operation[1], sql=False)
        harness.data.locked = locked
        return harness, operation[2](harness.service, database, bid)

    def _sql(self, operation, *, locked, database=_Harness.DATABASE, bid="7"):
        harness = _Harness(operation[1], sql=True)
        harness.data.locked = locked
        callbacks = []
        try:
            outcome = operation[5](harness.service, database, bid, callbacks.append)
        except Exception as exc:  # the blocked path under test
            outcome = exc
        return harness, outcome, callbacks

    def _assert_untouched(self, harness):
        self.assertEqual(
            (
                harness.executor.calls,
                harness.executor.requests,
                harness.calls,
                harness.reloads,
                harness.events.published,
                harness.provider.requests,
            ),
            (0, [], [], [], [], []),
        )

    def _assert_sql_queued_and_committed(self, harness, outcome, callbacks):
        self.assertEqual(outcome, 41)
        self.assertEqual(len(harness.provider.requests), 1)
        _request, execute, _callback = harness.provider.requests[0]
        self.assertEqual(callbacks, [])
        self.assertEqual(execute().outcome_status, MutationOutcomeStatus.COMMITTED)
        self.assertGreater(len(harness.calls), 0)

    def test_locked_active_bid_blocks_every_condition_operation_on_both_backends(self):
        for operation in self._operations():
            name = operation[0]
            if operation[2] is not None:
                with self.subTest(operation=name, backend="access", locked=False):
                    control, result = self._access(operation, locked=False)
                    self.assertEqual(self._summary(result), operation[3])
                    self.assertGreater(control.executor.calls, 0)
                with self.subTest(operation=name, backend="access", locked=True):
                    harness, result = self._access(operation, locked=True)
                    self.assertEqual(self._summary(result), operation[4])
                    self._assert_untouched(harness)
            with self.subTest(operation=name, backend="sql", locked=False):
                control, outcome, callbacks = self._sql(operation, locked=False)
                self._assert_sql_queued_and_committed(control, outcome, callbacks)
            with self.subTest(operation=name, backend="sql", locked=True):
                harness, outcome, callbacks = self._sql(operation, locked=True)
                self.assertIsInstance(outcome, ActiveBidLockedError)
                self.assertEqual(str(outcome), "The active bid is locked")
                self.assertEqual(callbacks, [])
                self._assert_untouched(harness)

    def test_a_locked_active_bid_of_another_database_is_not_blocked(self):
        for operation in self._operations():
            name = operation[0]
            if operation[2] is not None:
                with self.subTest(operation=name, backend="access"):
                    harness, result = self._access(
                        operation, locked=True, database=self.OTHER
                    )
                    self.assertEqual(self._summary(result), operation[3])
                    self.assertGreater(harness.executor.calls, 0)
            with self.subTest(operation=name, backend="sql"):
                harness, outcome, callbacks = self._sql(
                    operation, locked=True, database=self.OTHER
                )
                self._assert_sql_queued_and_committed(harness, outcome, callbacks)

    def test_another_bid_than_the_locked_active_bid_is_not_blocked(self):
        for operation in self._operations():
            name = operation[0]
            if operation[2] is not None:
                with self.subTest(operation=name, backend="access"):
                    harness, result = self._access(operation, locked=True, bid="8")
                    self.assertEqual(self._summary(result), operation[3])
                    self.assertGreater(harness.executor.calls, 0)
            with self.subTest(operation=name, backend="sql"):
                harness, outcome, callbacks = self._sql(operation, locked=True, bid="8")
                self._assert_sql_queued_and_committed(harness, outcome, callbacks)

    def test_queued_condition_updates_are_gated_whatever_fields_change(self):
        # Decision G3 (supersedes the F2 boundary pin that left a queued update without
        # a folder change to the UI): Access update_condition consults the guard for
        # every change, so queue_conditions_update does too. Gating only folder moves, or
        # only a truthy folder, would let these through.
        for changes in (
            {"cdn_type_uid": None},
            {"name": "N"},
            {"layer_uid": None},
            {"z_value": 1.5},
            {"folder_uid": "f1"},
        ):
            with self.subTest(changes=changes):
                harness = _Harness(
                    {"update_condition": UpdateConditionResultDto(success=True)},
                    sql=True,
                )
                harness.data.locked = True
                with self.assertRaises(ActiveBidLockedError):
                    harness.service.queue_conditions_update(
                        _Harness.DATABASE, "7", ["c1"], dict(changes), lambda _r: None
                    )
                self._assert_untouched(harness)

    def _ungated_operations(self):
        # Condition-type catalog edits are database-wide, not Bid-scoped: Access
        # save_condition_types_result never consults the guard, and neither does the SQL
        # queue entry point. Pinned so that neither side drifts alone.
        types = {
            "new": [{"uid": "nt", "name": "N"}],
            "updated": [],
            "deleted_uids": [],
        }
        return (
            "save condition types",
            {"save_condition_types": {"nt": "11"}},
            lambda s, d, b: s.save_condition_types_result(d, dict(types)),
            ({"nt": "11"}, True, True),
            lambda s, d, b, cb: s.queue_condition_types_save(d, dict(types), cb),
        )

    def test_condition_type_edits_are_never_lock_blocked_on_either_backend(self):
        name, script, access, expected, sql = self._ungated_operations()
        for situation, locked, database, bid in (
            ("locked active bid", True, _Harness.DATABASE, "7"),
            ("unlocked control", False, _Harness.DATABASE, "7"),
            ("locked bid in another database", True, self.OTHER, "7"),
            ("other bid in the same database", True, _Harness.DATABASE, "8"),
        ):
            with self.subTest(operation=name, backend="access", situation=situation):
                harness = _Harness(script, sql=False)
                harness.data.locked = locked
                result = access(harness.service, database, bid)
                self.assertEqual(self._summary(result), expected)
                self.assertGreater(harness.executor.calls, 0)
            with self.subTest(operation=name, backend="sql", situation=situation):
                harness = _Harness(script, sql=True)
                harness.data.locked = locked
                callbacks = []
                outcome = sql(harness.service, database, bid, callbacks.append)
                self._assert_sql_queued_and_committed(harness, outcome, callbacks)


class LayerAreaLockedBidParityTests(unittest.TestCase):
    """Decisions H2 and H3: every Bid-owned Layer and Area command is blocked on a
    status-locked ACTIVE Bid on both backends, exactly like the Access commands (see
    ConditionFolderLockedBidParityTests for the contract: Access reports the block in
    its result, the SQL queue_* entry points raise ActiveBidLockedError at submission
    with nothing queued, no callback and no event). Table: operation x backend x
    situation {locked active Bid, unlocked control, locked Bid of another database,
    other Bid of the same database}. Where an Access command takes no Bid (delete,
    reorder, rename and show of a Layer, page Area selection) it resolves the active Bid
    itself, so the 'other Bid' situation only exists on SQL, whose queue_* takes the Bid.
    The default (template) Layer commands are the pinned exception: Access consults only
    the write-blocked connection state, never the Bid lock, and the SQL queue_default_*
    entry points do not either."""

    OTHER = _ALTERNATE_DATABASES["other_database"]

    @staticmethod
    def _summary(result):
        if isinstance(result, WriteReloadResult):
            return (result.value, result.write_success, result.reload_success)
        if isinstance(result, BatchWriteResult):
            return (
                list(result.succeeded_uids),
                list(result.failed_uids),
                result.reload_success,
            )
        return result

    @staticmethod
    def _row(name, script, access, allowed, blocked, sql, access_bid=True):
        return SimpleNamespace(
            name=name,
            script=script,
            access=access,
            allowed=allowed,
            blocked=blocked,
            sql=sql,
            access_bid=access_bid,
        )

    # access_bid False: the Access command has no Bid argument (guard keyed on the
    # active Bid of the database).
    def _operations(self):
        row = self._row
        batch_ok = (["40", "41"], [], True)
        batch_blocked = ([], ["40", "41"], True)
        return (
            row(
                "insert layer",
                {"insert_layer": "L9"},
                lambda s, d, b: s.insert_layer_result(d, b, "Roads", 3),
                ("L9", True, True),
                (None, False, False),
                lambda s, d, b, cb: s.queue_layer_insert(d, b, "Roads", 3, cb),
            ),
            row(
                "delete layer",
                {},
                lambda s, d, b: s.delete_layer(d, "40"),
                True,
                False,
                lambda s, d, b, cb: s.queue_layer_delete(d, b, "40", cb),
                access_bid=False,
            ),
            row(
                "delete layers",
                {},
                lambda s, d, b: s.delete_layers(d, ["40", "41"]),
                batch_ok,
                batch_blocked,
                lambda s, d, b, cb: s.queue_layers_delete(d, b, ["40", "41"], cb),
                access_bid=False,
            ),
            row(
                "reorder layers",
                {},
                lambda s, d, b: s.swap_layer_sequence(d, "40", "41"),
                True,
                False,
                lambda s, d, b, cb: s.queue_layer_reorder(d, b, "40", "41", cb),
                access_bid=False,
            ),
            row(
                "rename layer",
                {},
                lambda s, d, b: s.update_layer_name(d, "40", "Roads"),
                True,
                False,
                lambda s, d, b, cb: s.queue_layer_rename(d, b, "40", "Roads", cb),
                access_bid=False,
            ),
            row(
                "show all layers",
                {},
                lambda s, d, b: s.update_all_layers_show(d, b, True, ["40", "41"]),
                True,
                False,
                lambda s, d, b, cb: s.queue_all_layers_show(
                    d, b, True, ["40", "41"], cb
                ),
            ),
            row(
                "hide all layers",
                {},
                lambda s, d, b: s.update_all_layers_show(d, b, False, ["40"]),
                True,
                False,
                lambda s, d, b, cb: s.queue_all_layers_show(d, b, False, ["40"], cb),
            ),
            row(
                "show one layer",
                {},
                lambda s, d, b: s.update_layer_show(d, "40", True),
                True,
                False,
                lambda s, d, b, cb: s.queue_page_settings(
                    d, b, "layer_show", [["40", True]], cb
                ),
                access_bid=False,
            ),
            row(
                "select a page area",
                {},
                lambda s, d, b: s.save_page_area(d, "20", "5"),
                True,
                False,
                lambda s, d, b, cb: s.queue_page_settings(
                    d, b, "area", [["20", "5"]], cb
                ),
                access_bid=False,
            ),
            row(
                "save bid areas",
                {"save_bid_areas": {"new_0": "11"}},
                lambda s, d, b: s.save_bid_areas_result(d, b, _area_changes()),
                ({"new_0": "11"}, True, True),
                (None, False, False),
                lambda s, d, b, cb: s.queue_bid_areas_save(d, b, _area_changes(), cb),
            ),
            row(
                "save bid areas without changes",
                {"save_bid_areas": {}},
                lambda s, d, b: s.save_bid_areas_result(
                    d, b, BidAreaChangeset(new=[], updated=[], deleted_uids=[])
                ),
                ({}, True, True),
                (None, False, False),
                lambda s, d, b, cb: s.queue_bid_areas_save(
                    d, b, BidAreaChangeset(new=[], updated=[], deleted_uids=[]), cb
                ),
            ),
        )

    def _access(self, operation, *, locked, database=_Harness.DATABASE, bid="7"):
        harness = _Harness(operation.script, sql=False)
        harness.data.locked = locked
        return harness, operation.access(harness.service, database, bid)

    def _sql(self, operation, *, locked, database=_Harness.DATABASE, bid="7"):
        harness = _Harness(operation.script, sql=True)
        harness.data.locked = locked
        callbacks = []
        try:
            outcome = operation.sql(harness.service, database, bid, callbacks.append)
        except Exception as exc:  # the blocked path under test
            outcome = exc
        return harness, outcome, callbacks

    _assert_untouched = ConditionFolderLockedBidParityTests._assert_untouched
    _assert_sql_queued_and_committed = (
        ConditionFolderLockedBidParityTests._assert_sql_queued_and_committed
    )

    def test_locked_active_bid_blocks_every_layer_and_area_operation_on_both_backends(
        self,
    ):
        operations = self._operations()
        self.assertEqual(len(operations), 11)
        for operation in operations:
            name = operation.name
            with self.subTest(operation=name, backend="access", locked=False):
                control, result = self._access(operation, locked=False)
                self.assertEqual(self._summary(result), operation.allowed)
                self.assertGreater(control.executor.calls, 0)
            with self.subTest(operation=name, backend="access", locked=True):
                harness, result = self._access(operation, locked=True)
                self.assertEqual(self._summary(result), operation.blocked)
                self._assert_untouched(harness)
            with self.subTest(operation=name, backend="sql", locked=False):
                control, outcome, callbacks = self._sql(operation, locked=False)
                self._assert_sql_queued_and_committed(control, outcome, callbacks)
            with self.subTest(operation=name, backend="sql", locked=True):
                harness, outcome, callbacks = self._sql(operation, locked=True)
                self.assertIsInstance(outcome, ActiveBidLockedError)
                self.assertEqual(str(outcome), "The active bid is locked")
                self.assertEqual(callbacks, [])
                self._assert_untouched(harness)

    def test_a_locked_active_bid_of_another_database_is_not_blocked(self):
        for operation in self._operations():
            with self.subTest(operation=operation.name, backend="access"):
                harness, result = self._access(
                    operation, locked=True, database=self.OTHER
                )
                self.assertEqual(self._summary(result), operation.allowed)
                self.assertGreater(harness.executor.calls, 0)
            with self.subTest(operation=operation.name, backend="sql"):
                harness, outcome, callbacks = self._sql(
                    operation, locked=True, database=self.OTHER
                )
                self._assert_sql_queued_and_committed(harness, outcome, callbacks)

    def test_another_bid_than_the_locked_active_bid_is_not_blocked(self):
        for operation in self._operations():
            if operation.access_bid:
                with self.subTest(operation=operation.name, backend="access"):
                    harness, result = self._access(operation, locked=True, bid="8")
                    self.assertEqual(self._summary(result), operation.allowed)
                    self.assertGreater(harness.executor.calls, 0)
            with self.subTest(operation=operation.name, backend="sql"):
                harness, outcome, callbacks = self._sql(operation, locked=True, bid="8")
                self._assert_sql_queued_and_committed(harness, outcome, callbacks)

    def test_bid_less_access_commands_resolve_the_active_bid_themselves(self):
        # Pins why those rows have no Access 'other Bid' situation: the guard is keyed
        # on the active Bid of the database, whatever Bid the caller means.
        for operation in self._operations():
            if operation.access_bid:
                continue
            with self.subTest(operation=operation.name):
                harness, result = self._access(operation, locked=True, bid="8")
                self.assertEqual(self._summary(result), operation.blocked)
                self._assert_untouched(harness)

    # Default (template) Layers belong to the database, not to a Bid.
    def _default_layer_operations(self):
        row = self._row
        return (
            row(
                "insert default layer",
                {"insert_layer": "L9"},
                lambda s, d, b: s.insert_default_layer_result(d, "Roads", 3),
                ("L9", True, True),
                None,
                lambda s, d, b, cb: s.queue_default_layer_insert(d, "Roads", 3, cb),
            ),
            row(
                "delete default layers",
                {},
                lambda s, d, b: s.delete_default_layers(d, ["40", "41"]),
                (["40", "41"], [], True),
                None,
                lambda s, d, b, cb: s.queue_default_layers_delete(d, ["40", "41"], cb),
            ),
            row(
                "rename default layer",
                {},
                lambda s, d, b: s.update_default_layer_name(d, "40", "Roads"),
                True,
                None,
                lambda s, d, b, cb: s.queue_default_layer_update(
                    d, "rename", {"layer_uid": "40", "name": "Roads"}, cb
                ),
            ),
            row(
                "show one default layer",
                {},
                lambda s, d, b: s.update_default_layer_show(d, "40", True),
                True,
                None,
                lambda s, d, b, cb: s.queue_default_layer_update(
                    d, "show", {"layer_uid": "40", "show": True}, cb
                ),
            ),
            row(
                "show all default layers",
                {},
                lambda s, d, b: s.update_all_default_layers_show(d, True),
                True,
                None,
                lambda s, d, b, cb: s.queue_default_layer_update(
                    d, "show_all", {"show": True}, cb
                ),
            ),
            row(
                "reorder default layers",
                {},
                lambda s, d, b: s.swap_default_layer_sequence(d, "40", "41"),
                True,
                None,
                lambda s, d, b, cb: s.queue_default_layer_update(
                    d, "reorder", {"layer_uid": "40", "neighbor_uid": "41"}, cb
                ),
            ),
        )

    def test_default_layer_commands_are_never_lock_blocked_on_either_backend(self):
        operations = self._default_layer_operations()
        self.assertEqual(len(operations), 6)
        for operation in operations:
            for situation, locked, database, bid in (
                ("locked active bid", True, _Harness.DATABASE, "7"),
                ("unlocked control", False, _Harness.DATABASE, "7"),
                ("locked bid in another database", True, self.OTHER, "7"),
                ("other bid in the same database", True, _Harness.DATABASE, "8"),
            ):
                with self.subTest(
                    operation=operation.name, backend="access", situation=situation
                ):
                    harness, result = self._access(
                        operation, locked=locked, database=database, bid=bid
                    )
                    self.assertEqual(self._summary(result), operation.allowed)
                    self.assertGreater(harness.executor.calls, 0)
                with self.subTest(
                    operation=operation.name, backend="sql", situation=situation
                ):
                    harness, outcome, callbacks = self._sql(
                        operation, locked=locked, database=database, bid=bid
                    )
                    self._assert_sql_queued_and_committed(harness, outcome, callbacks)

    def test_queue_page_setting_if_sql_refuses_a_locked_layer_or_area_write(self):
        # The deferred visibility/area pipeline asks queue_page_setting_if_sql, which
        # reports 'could not queue' as False (the caller restores the optimistic state);
        # a blocked write must take that path with one warning and nothing queued,
        # exactly like the Access fallback returning False.
        cases = (
            ("layer_show", "40", [True]),
            ("all_layers_show", "7", [True, ["40", "41"]]),
            ("area", "20", ["5"]),
        )
        for kind, resource_uid, values in cases:
            with self.subTest(kind=kind, locked=True):
                harness = _Harness(sql=True)
                harness.data.locked = True
                with self.assertLogs("test.project_write_harness", "WARNING") as logs:
                    queued = harness.service.queue_page_setting_if_sql(
                        _Harness.DATABASE, resource_uid, kind, list(values)
                    )
                self.assertIs(queued, False)
                self.assertEqual(harness.provider.requests, [])
                self.assertEqual(
                    logs.output,
                    [
                        "WARNING:test.project_write_harness:Queued page setting "
                        f"{kind} for {resource_uid} blocked: the active bid is locked"
                    ],
                )
            with self.subTest(kind=kind, locked=False):
                harness = _Harness(sql=True)
                queued = harness.service.queue_page_setting_if_sql(
                    _Harness.DATABASE, resource_uid, kind, list(values)
                )
                self.assertIs(queued, True)
                self.assertEqual(len(harness.provider.requests), 1)

    def test_queue_page_setting_if_sql_refuses_the_scale_page_setting_when_locked(self):
        # Decision P2 supersedes the H3 scope pin (only the Layer/Area kinds were gated,
        # the scale was still queued on a locked active Bid): every page setting is
        # refused now; PageSettingPlanLockedBidParityTests covers all kinds.
        harness = _Harness(sql=True)
        harness.data.locked = True
        queued = harness.service.queue_page_setting_if_sql(
            _Harness.DATABASE, "20", "scale", [1.0, 2.0]
        )
        self.assertIs(queued, False)
        self.assertEqual(harness.provider.requests, [])


class ProjectTreeCommandsLockedBidGuardTests(unittest.TestCase):
    """Decision P4: guard status of the project-tree structure commands while the
    active Bid (7 of C:/jobs/test.mdb, in project 3) is status-locked. Pins CURRENT
    behaviour: the UI keeps EDIT_PROJECT_TREE_STRUCTURE allowed, Access consults
    ActiveBidWriteGuard only for move_bids of the active Bid and delete_projects of its
    parent project; since decision Q1 the SQL queue_bids_move/queue_projects_delete are
    gated identically (ProjectTreeActiveBidMoveParityTests holds the full parity table)
    and every other SQL queue_* tree command stays ungated. Fake: use-case probes,
    executor, queue provider."""

    DATABASE = _Harness.DATABASE

    def _harness(self, *, sql, locked):
        harness = _Harness(sql=sql)
        harness.data.locked = locked
        harness.data.project_of_bid = "3"
        return harness

    @staticmethod
    def _access_commands(service):
        database = _Harness.DATABASE
        return {
            "delete_bids": lambda: service.delete_bids(database, ["7"]),
            "delete_projects of the active Bid's project": lambda: (
                service.delete_projects(database, ["3"])
            ),
            "delete_projects of another project": lambda: (
                service.delete_projects(database, ["4"])
            ),
            "create_project": lambda: service.create_project(database, "New"),
            "rename_project": lambda: service.rename_project(database, "3", "New"),
            "move_bids of the active Bid": lambda: (
                service.move_bids(database, ["7"], "4", "3")
            ),
            "move_bids of another Bid": lambda: (
                service.move_bids(database, ["8"], "4", "3")
            ),
            "duplicate_bid": lambda: service.duplicate_bid(database, "7"),
            "create_bid": lambda: service.create_bid(database, "3", {"name": "n"}),
        }

    # Access commands the guard rejects on a locked active Bid; every other row reaches
    # its use case exactly as when unlocked.
    _ACCESS_REJECTED = {
        "delete_projects of the active Bid's project",
        "move_bids of the active Bid",
    }

    def test_access_tree_commands_on_a_locked_active_bid(self):
        names = self._access_commands(self._harness(sql=False, locked=False).service)
        for name in names:
            for locked in (False, True):
                with self.subTest(command=name, locked=locked):
                    harness = self._harness(sql=False, locked=locked)
                    result = self._access_commands(harness.service)[name]()
                    if locked and name in self._ACCESS_REJECTED:
                        self.assertIs(result, False)
                        self.assertEqual(harness.calls, [])
                    else:
                        self.assertTrue(result)
                        self.assertEqual(len(harness.calls), 1)

    # Decision Q1 (changes the P4 pin): SQL now refuses the same two commands as Access.
    _SQL_REJECTED = {"queue_bids_move", "queue_projects_delete"}

    def test_sql_tree_commands_gate_only_move_and_project_delete_on_a_locked_active_bid(
        self,
    ):
        database = self.DATABASE

        def callback(_result):
            pass

        commands = {
            "queue_bids_delete": lambda s: s.queue_bids_delete(
                database, ["7"], callback
            ),
            "queue_projects_delete": lambda s: s.queue_projects_delete(
                database, ["3"], callback
            ),
            "queue_project_create": lambda s: s.queue_project_create(
                database, "New", callback
            ),
            "queue_project_rename": lambda s: s.queue_project_rename(
                database, "3", "New", callback
            ),
            "queue_bids_move": lambda s: s.queue_bids_move(
                database, ["7"], "4", callback, original_project_uid="3"
            ),
            "queue_bids_duplicate": lambda s: s.queue_bids_duplicate(
                database, ["7"], "3", callback
            ),
            "queue_bid_create": lambda s: s.queue_bid_create(
                database, "3", {"name": "n"}, callback
            ),
        }
        for name, command in commands.items():
            for locked in (False, True):
                with self.subTest(command=name, locked=locked):
                    harness = self._harness(sql=True, locked=locked)
                    if locked and name in self._SQL_REJECTED:
                        with self.assertRaises(ActiveBidLockedError):
                            command(harness.service)
                        self.assertEqual(harness.provider.requests, [])
                    else:
                        self.assertIsInstance(command(harness.service), int)
                        self.assertEqual(len(harness.provider.requests), 1)


class ProjectTreeActiveBidMoveParityTests(unittest.TestCase):
    """Decisions Q1/Q3a: moving, trashing and restoring the status-locked ACTIVE Bid
    (7 of C:/jobs/test.mdb, in project 3) and deleting the project that contains it are
    refused on BOTH backends exactly like Access move_bids/delete_projects: Access
    returns False with its use case untouched, the SQL queue_* entry points raise
    ActiveBidLockedError at submission with nothing queued. Every other situation
    proceeds on both backends: unlocked control, a locked active Bid of ANOTHER
    database, and a DIFFERENT non-active Bid while Bid 7 is locked. Permanent Bid
    delete (delete_bids/queue_bids_delete) is unguarded on both backends. Fake:
    use-case probes, strict executor, queue provider (no live SQL Server/Access)."""

    DATABASE = _Harness.DATABASE
    # situation -> (lock the active Bid?, database of the active Bid, Bid uid used by
    # the move/trash/restore commands, project uid used by delete_projects)
    _SITUATIONS = {
        "target is the locked active Bid": (True, "C:/jobs/test.mdb", "7", "3"),
        "unlocked control": (False, "C:/jobs/test.mdb", "7", "3"),
        "locked Bid in another database": (True, "C:/jobs/other.mdb", "7", "3"),
        "different non-active Bid while another is locked": (
            True,
            "C:/jobs/test.mdb",
            "8",
            "4",
        ),
    }
    _REFUSED = {"target is the locked active Bid"}

    def _harness(self, *, sql, locked, active_database):
        harness = _Harness(sql=sql)
        harness.data.locked = locked
        harness.data.bid_ref = BidRef(active_database, "7")
        harness.data.project_of_bid = "3"
        return harness

    @staticmethod
    def _commands(service, bid_uid, project_uid, *, sql):
        database = _Harness.DATABASE

        def callback(_result):
            pass

        if sql:
            return {
                "move": lambda: service.queue_bids_move(
                    database, [bid_uid], "4", callback, original_project_uid="3"
                ),
                "trash": lambda: service.queue_bids_move(
                    database, [bid_uid], "1", callback, original_project_uid="3"
                ),
                "restore": lambda: service.queue_bids_move(
                    database, [bid_uid], "3", callback, original_project_uid="1"
                ),
                "batch move": lambda: service.queue_bids_move(
                    database, ["9", bid_uid], "4", callback, original_project_uid="3"
                ),
                "delete_projects": lambda: service.queue_projects_delete(
                    database, [project_uid], callback
                ),
                "delete_bids": lambda: service.queue_bids_delete(
                    database, [bid_uid], callback
                ),
            }
        return {
            "move": lambda: service.move_bids(database, [bid_uid], "4", "3"),
            "trash": lambda: service.move_bids(database, [bid_uid], "1", "3"),
            "restore": lambda: service.move_bids(database, [bid_uid], "3"),
            "batch move": lambda: service.move_bids(database, ["9", bid_uid], "4", "3"),
            "delete_projects": lambda: service.delete_projects(database, [project_uid]),
            "delete_bids": lambda: service.delete_bids(database, [bid_uid]),
        }

    def test_parity_table_over_backends_commands_and_lock_situations(self):
        # delete_bids is the permanent delete: unguarded on Access and SQL.
        always_reaches = {"delete_bids"}
        for sql in (False, True):
            backend = "sql" if sql else "access"
            for situation, (
                locked,
                active_db,
                bid_uid,
                project_uid,
            ) in self._SITUATIONS.items():
                names = self._commands(
                    _Harness(sql=sql).service, bid_uid, project_uid, sql=sql
                )
                for name in names:
                    with self.subTest(
                        backend=backend, situation=situation, command=name
                    ):
                        harness = self._harness(
                            sql=sql, locked=locked, active_database=active_db
                        )
                        command = self._commands(
                            harness.service, bid_uid, project_uid, sql=sql
                        )[name]
                        refused = (
                            situation in self._REFUSED and name not in always_reaches
                        )
                        if sql and refused:
                            with self.assertRaises(ActiveBidLockedError):
                                command()
                            self.assertEqual(harness.provider.requests, [])
                        elif sql:
                            self.assertIsInstance(command(), int)
                            self.assertEqual(len(harness.provider.requests), 1)
                        elif refused:
                            self.assertIs(command(), False)
                            self.assertEqual(harness.calls, [])
                            self.assertEqual(harness.executor.requests, [])
                        else:
                            self.assertTrue(command())
                            self.assertEqual(len(harness.calls), 1)

    def test_sql_batch_with_the_active_bid_is_refused_whole_and_other_batches_proceed(
        self,
    ):
        # Access refuses a move batch that contains the active locked Bid as a whole
        # (any()); the SQL gate must not queue the other Bids of that batch either.
        database = self.DATABASE
        for bid_uids, refused in (
            (["8", "7", "9"], True),
            (["7", "8"], True),
            (["8", "9"], False),
        ):
            with self.subTest(bid_uids=bid_uids):
                harness = self._harness(sql=True, locked=True, active_database=database)
                if refused:
                    with self.assertRaises(ActiveBidLockedError):
                        harness.service.queue_bids_move(
                            database, bid_uids, "4", lambda _r: None
                        )
                    self.assertEqual(harness.provider.requests, [])
                else:
                    harness.service.queue_bids_move(
                        database, bid_uids, "4", lambda _r: None
                    )
                    self.assertEqual(len(harness.provider.requests), 1)
        harness = self._harness(sql=False, locked=True, active_database=database)
        self.assertIs(harness.service.move_bids(database, ["8", "7"], "4"), False)
        self.assertEqual(harness.calls, [])

    def test_sql_project_delete_is_refused_only_for_the_project_of_the_active_bid(
        self,
    ):
        database = self.DATABASE
        harness = self._harness(sql=True, locked=True, active_database=database)
        with self.assertRaises(ActiveBidLockedError):
            harness.service.queue_projects_delete(database, ["4", "3"], lambda _r: None)
        self.assertEqual(harness.provider.requests, [])
        harness.service.queue_projects_delete(database, ["4"], lambda _r: None)
        self.assertEqual(len(harness.provider.requests), 1)
        harness.data.locked = False
        harness.service.queue_projects_delete(database, ["3"], lambda _r: None)
        self.assertEqual(len(harness.provider.requests), 2)


class PageSettingPlanLockedBidParityTests(unittest.TestCase):
    """Decision P2/P3: every page-setting kind and every plan command (property kinds,
    geometry, delete, paste) is blocked on a status-locked ACTIVE Bid on both backends,
    exactly like the Access commands (see ConditionFolderLockedBidParityTests for the
    contract: Access reports the block in its result, the SQL queue_* entry points
    raise ActiveBidLockedError at submission with nothing queued, no callback and no
    event). Table: operation x backend x situation {locked active Bid, unlocked
    control, locked Bid of another database, other Bid of the same database}. The
    Access page-setting commands take no Bid (guard keyed on the active Bid of the
    database), so their 'other Bid' situation only exists on SQL, whose queue_* takes
    the Bid; the Access plan commands take the Bid. Layer/Area kinds (layer_show,
    area) are covered by LayerAreaLockedBidParityTests. Placement is gated at
    execution time on both backends (see the placement test); the client-local
    bid_selected_page/view_state settings never enter the SQL queue."""

    OTHER = _ALTERNATE_DATABASES["other_database"]
    PAGE_KINDS = (
        "scale",
        "show_mode",
        "overlay_image",
        "overlay_rect",
        "invert",
        "bitonal",
        "image_adjustments",
        "name",
    )
    PROPERTY_KINDS = (
        "takeoff_text",
        "takeoff_area",
        "takeoff_condition",
        "takeoff_negative",
        "takeoff_curve",
        "annotation_text",
        "annotation_style",
    )

    @staticmethod
    def _summary(result):
        if isinstance(result, MutationExecutionResult):
            return result.outcome_status.value
        if isinstance(result, WriteReloadResult):
            return (result.value, result.write_success, result.reload_success)
        return result

    @staticmethod
    def _row(
        name, script, access, allowed, blocked, sql, access_bid, setup=None, owned=False
    ):
        return SimpleNamespace(
            name=name,
            script=script,
            access=access,
            allowed=allowed,
            blocked=blocked,
            sql=sql,
            access_bid=access_bid,
            setup=setup,
            owned=owned,
        )

    def _page_operations(self):
        row = self._row
        yes, no = True, False

        def page(name, kind, access, allowed, blocked, updates):
            return row(
                name,
                {},
                access,
                allowed,
                blocked,
                lambda s, d, b, cb: s.queue_page_settings(d, b, kind, updates, cb),
                False,
            )

        return (
            page(
                "scale",
                "scale",
                lambda s, d, b: s.save_page_scale(d, "20", 1.0, 96.5),
                yes,
                no,
                [["20", 1.0, 96.5], ["21", 1.0, 96.5]],
            ),
            page(
                "show_mode",
                "show_mode",
                lambda s, d, b: s.save_page_show_mode(d, "20", 2),
                yes,
                no,
                [["20", 2]],
            ),
            page(
                "overlay_image",
                "overlay_image",
                lambda s, d, b: s.save_page_overlay_image(d, "20", "C:/o.png"),
                yes,
                no,
                [["20", "C:/o.png"]],
            ),
            page(
                "overlay_rect",
                "overlay_rect",
                lambda s, d, b: s.save_page_overlay_rect_result(
                    d, "20", (1.0, 2.0, 3.0, 4.0)
                ),
                (None, True, True),
                (None, False, False),
                [["20", [1.0, 2.0, 3.0, 4.0]]],
            ),
            page(
                "invert",
                "invert",
                lambda s, d, b: s.save_page_invert(d, "20", True),
                yes,
                no,
                [["20", True]],
            ),
            page(
                "bitonal",
                "bitonal",
                lambda s, d, b: s.save_page_bitonal(d, "20", False),
                yes,
                no,
                [["20", False]],
            ),
            page(
                "image_adjustments",
                "image_adjustments",
                lambda s, d, b: s.save_page_image_adjustments(
                    d, ["20", "21"], 90, True, False, True, False
                ),
                yes,
                no,
                [
                    ["20", 90, True, False, True, False],
                    ["21", 90, True, False, True, False],
                ],
            ),
            page(
                "name",
                "name",
                lambda s, d, b: s.save_page_name(d, "20", "Sheet"),
                yes,
                no,
                [["20", "Sheet"]],
            ),
        )

    def _plan_operations(self):
        row = self._row
        committed, rejected = "committed", "rejected"
        guard = lambda harness: setattr(harness.tokens, "guard", True)

        def properties(kind, updates):
            return row(
                f"properties {kind}",
                {},
                lambda s, d, b: s.execute_plan_properties_local(d, b, kind, updates),
                committed,
                rejected,
                lambda s, d, b, cb: s.queue_plan_properties(d, b, kind, updates, cb),
                True,
                guard,
                kind.startswith("takeoff_"),
            )

        def paste(destination):
            return replace(
                _cross_bid_paste_payload(), destination_bid_uid=str(destination)
            )

        paste_script = {
            "insert_takeoffs": _Seq(["p-new"], ["h-new"]),
            "insert_annotations": _Seq(["named-new"], ["rect-new"]),
            ("duplicate_conditions", "execute_to_bid"): {"c1": "c9"},
        }
        return (
            properties("takeoff_text", [("30", {"Text": "T"})]),
            properties("takeoff_area", [("30", "5"), ("32", "0"), ("31", "5")]),
            properties("takeoff_condition", [("30", "10"), ("32", "10")]),
            properties("takeoff_negative", [("30", True), ("32", False)]),
            properties("takeoff_curve", [("30", [1, 2], 3)]),
            properties("annotation_text", [("a1", "rect", {"Text": "T"})]),
            properties("annotation_style", [("a1", "rect", {"color": "#112233"})]),
            row(
                "geometry",
                {},
                lambda s, d, b: s.execute_plan_geometry_local(
                    d,
                    b,
                    takeoff_positions=[("30", [1, 2])],
                    takeoff_rotations=[("30", 90)],
                    annotation_positions=[("a1", "rect", [1, 2, 3, 4])],
                    page_uids=("20",),
                ),
                committed,
                rejected,
                lambda s, d, b, cb: s.queue_plan_geometry(
                    d,
                    b,
                    cb,
                    takeoff_positions=[("30", [1, 2])],
                    takeoff_rotations=[("30", 90)],
                    annotation_positions=[("a1", "rect", [1, 2, 3, 4])],
                    page_uids=("20",),
                ),
                True,
            ),
            row(
                "delete",
                {},
                lambda s, d, b: s.execute_plan_items_delete_local(
                    d, b, ["30", "31"], [("a1", "rect")], page_uids=("20",)
                ),
                committed,
                rejected,
                lambda s, d, b, cb: s.queue_plan_items_delete(
                    d, b, ["30", "31"], [("a1", "rect")], cb, page_uids=("20",)
                ),
                True,
            ),
            row(
                "paste",
                paste_script,
                lambda s, d, b: s.execute_plan_items_paste_local(d, paste(b)),
                committed,
                rejected,
                lambda s, d, b, cb: s.queue_plan_items_paste(d, paste(b), cb),
                True,
            ),
        )

    def _operations(self):
        return self._page_operations() + self._plan_operations()

    def _access(self, operation, *, locked, database=_Harness.DATABASE, bid="7"):
        harness = _Harness(operation.script, sql=False)
        harness.data.locked = locked
        return harness, operation.access(harness.service, database, bid)

    def _sql(self, operation, *, locked, database=_Harness.DATABASE, bid="7"):
        harness = _Harness(operation.script, sql=True)
        harness.data.locked = locked
        if operation.setup is not None:
            operation.setup(harness)
        callbacks = []
        try:
            outcome = operation.sql(harness.service, database, bid, callbacks.append)
        except Exception as exc:  # the blocked path under test
            outcome = exc
        return harness, outcome, callbacks

    _assert_untouched = ConditionFolderLockedBidParityTests._assert_untouched
    _assert_sql_queued_and_committed = (
        ConditionFolderLockedBidParityTests._assert_sql_queued_and_committed
    )
    OWNERSHIP = "The property mutation no longer owns the current Bid."

    def _assert_not_blocked(self, operation, access_result, access_harness, sql_result):
        # A Takeoff property mutation is only accepted for the Bid currently loaded
        # (it captures the Takeoffs' ownership from it), so for another Bid or database
        # both backends fail on that precondition instead of on the lock; the table
        # asserts exactly that (a lock block would be REJECTED / ActiveBidLockedError).
        harness, outcome, callbacks = sql_result
        if operation.owned:
            self.assertEqual(self._summary(access_result), "failed_before_commit")
            self.assertEqual(access_result.message, self.OWNERSHIP)
            self.assertEqual(access_harness.executor.calls, 0)
            self.assertNotIsInstance(outcome, ActiveBidLockedError)
            self.assertIsInstance(outcome, ValueError)
            self.assertEqual(str(outcome), self.OWNERSHIP)
            self.assertEqual(harness.provider.requests, [])
            return
        self.assertEqual(self._summary(access_result), operation.allowed)
        self.assertGreater(access_harness.executor.calls, 0)
        self._assert_sql_queued_and_committed(harness, outcome, callbacks)

    def test_the_table_covers_every_page_setting_and_plan_property_kind(self):
        operations = self._operations()
        self.assertEqual(
            [operation.name for operation in self._page_operations()],
            list(self.PAGE_KINDS),
        )
        self.assertEqual(
            [
                operation.name
                for operation in self._plan_operations()
                if operation.name.startswith("properties ")
            ],
            [f"properties {kind}" for kind in self.PROPERTY_KINDS],
        )
        self.assertEqual(len(operations), 8 + 7 + 3)
        # The remaining two kinds of the page-setting vocabulary are in the Layer/Area
        # table; any other kind is not part of the vocabulary.
        harness = _Harness(sql=True)
        for kind in (*self.PAGE_KINDS, "area", "layer_show"):
            with self.subTest(kind=kind):
                harness.service.queue_page_settings(
                    _Harness.DATABASE, "7", kind, [["20", "5"]], lambda _r: None
                )
        with self.assertRaises(ValueError):
            harness.service.queue_page_settings(
                _Harness.DATABASE, "7", "view_state", [["20", "5"]], lambda _r: None
            )

    def test_locked_active_bid_blocks_every_page_setting_and_plan_command_on_both_backends(
        self,
    ):
        for operation in self._operations():
            name = operation.name
            with self.subTest(operation=name, backend="access", locked=False):
                control, result = self._access(operation, locked=False)
                self.assertEqual(self._summary(result), operation.allowed)
                self.assertGreater(control.executor.calls, 0)
            with self.subTest(operation=name, backend="access", locked=True):
                harness, result = self._access(operation, locked=True)
                self.assertEqual(self._summary(result), operation.blocked)
                self._assert_untouched(harness)
            with self.subTest(operation=name, backend="sql", locked=False):
                control, outcome, callbacks = self._sql(operation, locked=False)
                self._assert_sql_queued_and_committed(control, outcome, callbacks)
            with self.subTest(operation=name, backend="sql", locked=True):
                harness, outcome, callbacks = self._sql(operation, locked=True)
                self.assertIsInstance(outcome, ActiveBidLockedError)
                self.assertEqual(str(outcome), "The active bid is locked")
                self.assertEqual(callbacks, [])
                self._assert_untouched(harness)

    def test_a_locked_active_bid_of_another_database_is_not_blocked(self):
        for operation in self._operations():
            with self.subTest(operation=operation.name):
                access_harness, access = self._access(
                    operation, locked=True, database=self.OTHER
                )
                sql = self._sql(operation, locked=True, database=self.OTHER)
                self._assert_not_blocked(operation, access, access_harness, sql)

    def test_another_bid_than_the_locked_active_bid_is_not_blocked(self):
        for operation in self._operations():
            if not operation.access_bid:
                with self.subTest(operation=operation.name):
                    harness, outcome, callbacks = self._sql(
                        operation, locked=True, bid="8"
                    )
                    self._assert_sql_queued_and_committed(harness, outcome, callbacks)
                continue
            with self.subTest(operation=operation.name):
                access_harness, access = self._access(operation, locked=True, bid="8")
                sql = self._sql(operation, locked=True, bid="8")
                self._assert_not_blocked(operation, access, access_harness, sql)

    def test_bid_less_access_page_settings_resolve_the_active_bid_themselves(self):
        # Pins why the page-setting rows have no Access 'other Bid' situation: the
        # guard is keyed on the active Bid of the database, whatever Bid the caller
        # means (the same rule as the Layer/Area commands without a Bid argument).
        for operation in self._page_operations():
            with self.subTest(operation=operation.name):
                harness, result = self._access(operation, locked=True, bid="8")
                self.assertEqual(self._summary(result), operation.blocked)
                self._assert_untouched(harness)

    def test_takeoff_placement_is_gated_at_execution_on_both_backends(self):
        # Pin: placement is not refused at queue time on SQL; the shared
        # _insert_takeoffs_mutation rejects it when the queued work runs (the caller's
        # callback then receives a REJECTED result and removes its preview), exactly
        # like Access insert_takeoffs_result returns a failed result.
        specs = _plan_specs()
        for locked in (False, True):
            with self.subTest(backend="access", locked=locked):
                harness = _Harness({"insert_takeoffs": ["101", "102"]}, sql=False)
                harness.data.locked = locked
                result = harness.service.insert_takeoffs_result(
                    _Harness.DATABASE, "7", specs
                )
                self.assertEqual(
                    (result.value, result.write_success),
                    ((["101", "102"], True) if not locked else ([], False)),
                )
                self.assertEqual(
                    [name for name, *_rest in harness.calls],
                    ["insert_takeoffs"] if not locked else [],
                )
            with self.subTest(backend="sql", locked=locked):
                harness = _Harness({"insert_takeoffs": ["101", "102"]}, sql=True)
                harness.data.locked = locked
                callbacks = []
                sequence = harness.service.queue_takeoff_placement(
                    _Harness.DATABASE,
                    "7",
                    specs,
                    "7b3c5ac1-e623-44aa-8203-26a0125873b9",
                    callbacks.append,
                )
                self.assertEqual(sequence, 41)
                self.assertEqual(len(harness.provider.requests), 1)
                execution = harness.provider.requests[0][1]()
                self.assertEqual(
                    execution.outcome_status,
                    (
                        MutationOutcomeStatus.REJECTED
                        if locked
                        else MutationOutcomeStatus.COMMITTED
                    ),
                )
                self.assertEqual(
                    [name for name, *_rest in harness.calls],
                    [] if locked else ["insert_takeoffs"],
                )
                self.assertEqual(callbacks, [])

    def test_queue_page_setting_if_sql_refuses_every_locked_page_setting_kind(self):
        # The page-setting entry used by the deferred pipeline, the scale handlers and
        # the rename/overlay/adjust callers reports 'could not queue' as False with one
        # warning and nothing queued, for every kind; the unlocked control queues.
        cases = (
            ("scale", [1.0, 2.0]),
            ("show_mode", [2]),
            ("overlay_image", ["C:/o.png"]),
            ("overlay_rect", [[1.0, 2.0, 3.0, 4.0]]),
            ("invert", [True]),
            ("bitonal", [False]),
            ("image_adjustments", [90, True, False, True, False]),
            ("name", ["Sheet"]),
        )
        self.assertEqual([kind for kind, _values in cases], list(self.PAGE_KINDS))
        for kind, values in cases:
            with self.subTest(kind=kind, locked=True):
                harness = _Harness(sql=True)
                harness.data.locked = True
                with self.assertLogs("test.project_write_harness", "WARNING") as logs:
                    queued = harness.service.queue_page_setting_if_sql(
                        _Harness.DATABASE, "20", kind, list(values)
                    )
                self.assertIs(queued, False)
                self.assertEqual(harness.provider.requests, [])
                self.assertEqual(
                    logs.output,
                    [
                        "WARNING:test.project_write_harness:Queued page setting "
                        f"{kind} for 20 blocked: the active bid is locked"
                    ],
                )
            with self.subTest(kind=kind, locked=False):
                harness = _Harness(sql=True)
                self.assertIs(
                    harness.service.queue_page_setting_if_sql(
                        _Harness.DATABASE, "20", kind, list(values)
                    ),
                    True,
                )
                self.assertEqual(len(harness.provider.requests), 1)

    def test_client_local_page_settings_never_enter_the_sql_queue_on_a_locked_bid(self):
        # Pin: bid_selected_page and view_state are client-local; the SQL entry point
        # refuses them with a ValueError (never a lock block, never queued), locked or
        # not, so there is nothing to gate.
        for kind in ("bid_selected_page", "view_state"):
            for locked in (True, False):
                with self.subTest(kind=kind, locked=locked):
                    harness = _Harness(sql=True)
                    harness.data.locked = locked
                    with self.assertRaises(ValueError):
                        harness.service.queue_page_setting_if_sql(
                            _Harness.DATABASE, "20", kind, ["x"]
                        )
                    self.assertEqual(harness.provider.requests, [])


class CoverSheetPagesDeleteLockedBidParityTests(unittest.TestCase):
    """Decision Q2/Q3b: save_cover_sheet / queue_cover_sheet_save and delete_pages /
    queue_pages_delete are blocked on a status-locked ACTIVE Bid on both backends (see
    ConditionFolderLockedBidParityTests for the contract: Access reports the block in
    its result, the SQL queue_* entry points raise ActiveBidLockedError at submission
    with nothing queued, no callback and no event). Table: operation x backend x
    situation {locked active Bid, unlocked control, locked Bid of another database,
    other Bid of the same database}. The Cover Sheet save carries the Bid on both
    backends (the whole payload, pages, folders and Bid settings, is one write keyed on
    it). Access delete_pages takes no Bid (guard keyed on the active Bid of the
    database), so its 'other Bid' situation only exists on SQL; SQL keys the guard on
    EACH owning Bid of the requested pages (resolved from the hierarchy, falling back
    to the Bid the request names for a page the model does not know) and refuses the
    whole request when any of them is the locked active Bid."""

    OTHER = _ALTERNATE_DATABASES["other_database"]
    COVER_UPDATES = {
        "job_name": "N",
        "deleted_page_uids": ["20"],
        "pages": [{"uid": "21", "name": "P"}, {"uid": None, "name": "New"}],
        "folders": [{"uid": "f1", "name": "F"}],
    }

    def _operations(self):
        def own_pages(harness, bid):
            harness.data.page_owners = {"20": bid, "21": bid}

        return (
            SimpleNamespace(
                name="cover sheet",
                access=lambda s, d, b: s.save_cover_sheet(
                    d, b, {"job_name": "N", "bid_no": "2"}
                ),
                sql=lambda s, d, b, cb: s.queue_cover_sheet_save(
                    d, b, deepcopy(self.COVER_UPDATES), cb
                ),
                access_bid=True,
                setup=None,
            ),
            SimpleNamespace(
                name="delete pages",
                access=lambda s, d, b: s.delete_pages(d, ["20", "21"]),
                sql=lambda s, d, b, cb: s.queue_pages_delete(d, b, ["20", "21"], cb),
                access_bid=False,
                setup=own_pages,
            ),
        )

    def _access(self, operation, *, locked, database=_Harness.DATABASE, bid="7"):
        harness = _Harness(sql=False)
        harness.data.locked = locked
        return harness, operation.access(harness.service, database, bid)

    def _sql(self, operation, *, locked, database=_Harness.DATABASE, bid="7"):
        harness = _Harness(sql=True)
        harness.data.locked = locked
        if operation.setup is not None:
            operation.setup(harness, bid)
        callbacks = []
        try:
            outcome = operation.sql(harness.service, database, bid, callbacks.append)
        except Exception as exc:  # the blocked path under test
            outcome = exc
        return harness, outcome, callbacks

    _assert_untouched = ConditionFolderLockedBidParityTests._assert_untouched
    _assert_sql_queued_and_committed = (
        ConditionFolderLockedBidParityTests._assert_sql_queued_and_committed
    )

    def _assert_blocked(self, harness, outcome, callbacks):
        self.assertIsInstance(outcome, ActiveBidLockedError)
        self.assertEqual(str(outcome), "The active bid is locked")
        self.assertEqual(callbacks, [])
        self._assert_untouched(harness)

    def test_the_table_covers_the_cover_sheet_save_and_the_pages_delete(self):
        self.assertEqual(
            [operation.name for operation in self._operations()],
            ["cover sheet", "delete pages"],
        )

    def test_locked_active_bid_blocks_cover_sheet_save_and_pages_delete_on_both_backends(
        self,
    ):
        for operation in self._operations():
            name = operation.name
            with self.subTest(operation=name, backend="access", locked=False):
                control, result = self._access(operation, locked=False)
                self.assertIs(result, True)
                self.assertGreater(control.executor.calls, 0)
            with self.subTest(operation=name, backend="access", locked=True):
                harness, result = self._access(operation, locked=True)
                self.assertIs(result, False)
                self._assert_untouched(harness)
            with self.subTest(operation=name, backend="sql", locked=False):
                control, outcome, callbacks = self._sql(operation, locked=False)
                self._assert_sql_queued_and_committed(control, outcome, callbacks)
            with self.subTest(operation=name, backend="sql", locked=True):
                harness, outcome, callbacks = self._sql(operation, locked=True)
                self._assert_blocked(harness, outcome, callbacks)

    def test_a_locked_active_bid_of_another_database_is_not_blocked(self):
        for operation in self._operations():
            with self.subTest(operation=operation.name, backend="access"):
                harness, result = self._access(
                    operation, locked=True, database=self.OTHER
                )
                self.assertIs(result, True)
                self.assertGreater(harness.executor.calls, 0)
            with self.subTest(operation=operation.name, backend="sql"):
                harness, outcome, callbacks = self._sql(
                    operation, locked=True, database=self.OTHER
                )
                self._assert_sql_queued_and_committed(harness, outcome, callbacks)

    def test_another_bid_than_the_locked_active_bid_is_not_blocked(self):
        for operation in self._operations():
            if operation.access_bid:
                with self.subTest(operation=operation.name, backend="access"):
                    harness, result = self._access(operation, locked=True, bid="8")
                    self.assertIs(result, True)
                    self.assertGreater(harness.executor.calls, 0)
            with self.subTest(operation=operation.name, backend="sql"):
                harness, outcome, callbacks = self._sql(operation, locked=True, bid="8")
                self._assert_sql_queued_and_committed(harness, outcome, callbacks)
                request = harness.provider.requests[0][0]
                self.assertEqual(request.bid_uid, 8)

    def test_access_delete_pages_resolves_the_active_bid_itself(self):
        # Pin why the delete-pages row has no Access 'other Bid' situation: Access
        # delete_pages has no Bid argument, so its guard is keyed on the active Bid of
        # the database whichever Bid the pages belong to (accepted difference: SQL
        # keys on each owning Bid, see the tests below).
        operation = self._operations()[1]
        harness, result = self._access(operation, locked=True, bid="8")
        self.assertIs(result, False)
        self._assert_untouched(harness)

    def _delete(self, owners, declared, pages, *, locked=True, database=None):
        harness = _Harness(sql=True)
        harness.data.locked = locked
        harness.data.page_owners = dict(owners)
        callbacks = []
        try:
            outcome = harness.service.queue_pages_delete(
                database or _Harness.DATABASE, declared, list(pages), callbacks.append
            )
        except Exception as exc:  # the blocked path under test
            outcome = exc
        return harness, outcome, callbacks

    def test_a_pages_request_with_any_page_of_the_locked_bid_is_refused_as_a_whole(
        self,
    ):
        # Pages of three Bids: the locked active Bid 7 owns one of them, wherever it
        # sits in the request and whichever Bid the request names.
        for owners in (
            {"20": "7", "21": "8", "22": "9"},
            {"20": "7", "21": "5", "22": "6"},
        ):
            for pages in (
                ["20", "21"],
                ["21", "20"],
                ["21", "22", "20"],
                ["20", "21", "22"],
            ):
                for declared in ("7", "8", "9"):
                    with self.subTest(owners=owners, pages=pages, declared=declared):
                        harness, outcome, callbacks = self._delete(
                            owners, declared, pages
                        )
                        self._assert_blocked(harness, outcome, callbacks)
        with self.subTest("access reference"):
            harness = _Harness(sql=False)
            harness.data.locked = True
            result = harness.service.delete_pages(_Harness.DATABASE, ["20", "21"])
            self.assertIs(result, False)
            self._assert_untouched(harness)

    def test_a_pages_request_of_other_bids_only_is_queued_whichever_bid_it_names(self):
        owners = {"20": "8", "21": "9", "22": "8"}
        for pages in (["20", "21"], ["22"], ["21", "22", "20"]):
            for declared in ("7", "8"):
                with self.subTest(pages=pages, declared=declared):
                    harness, outcome, callbacks = self._delete(owners, declared, pages)
                    self._assert_sql_queued_and_committed(harness, outcome, callbacks)

    def test_mixed_bid_pages_request_is_queued_when_no_bid_is_locked_or_in_another_database(
        self,
    ):
        owners = {"20": "7", "21": "8"}
        for label, kwargs in (
            ("unlocked", {"locked": False}),
            ("other database", {"database": self.OTHER}),
        ):
            with self.subTest(label):
                harness, outcome, callbacks = self._delete(
                    owners, "8", ["20", "21"], **kwargs
                )
                self._assert_sql_queued_and_committed(harness, outcome, callbacks)

    def test_the_hierarchy_is_only_consulted_when_the_database_has_a_locked_active_bid(
        self,
    ):
        for label, kwargs in (
            ("unlocked", {"locked": False}),
            ("other database", {"database": self.OTHER}),
        ):
            with self.subTest(label):
                harness = _Harness(sql=True)
                harness.data.locked = kwargs.get("locked", True)
                lookups = []
                harness.data.find_owning_bid_uid_for_page = (
                    lambda *args: lookups.append(args)
                )
                harness.service.queue_pages_delete(
                    kwargs.get("database", _Harness.DATABASE),
                    "8",
                    ["20", "21"],
                    lambda _result: None,
                )
                self.assertEqual(lookups, [])
        with self.subTest("locked control"):
            harness = _Harness(sql=True)
            harness.data.locked = True
            lookups = []
            harness.data.find_owning_bid_uid_for_page = lambda *args: lookups.append(
                args
            )
            harness.service.queue_pages_delete(
                _Harness.DATABASE, "8", ["20", "21"], lambda _result: None
            )
            self.assertEqual(
                lookups, [(_Harness.DATABASE, "20"), (_Harness.DATABASE, "21")]
            )

    def test_a_page_the_model_does_not_know_belongs_to_the_bid_the_request_names(self):
        for declared, blocked in (("7", True), ("8", False)):
            with self.subTest(declared=declared):
                harness, outcome, callbacks = self._delete({}, declared, ["20", "21"])
                if blocked:
                    self._assert_blocked(harness, outcome, callbacks)
                else:
                    self._assert_sql_queued_and_committed(harness, outcome, callbacks)
        with self.subTest("unknown page next to a page of another Bid"):
            harness, outcome, callbacks = self._delete({"20": "8"}, "7", ["20", "21"])
            self._assert_blocked(harness, outcome, callbacks)
        with self.subTest(
            "unknown page next to a page of another Bid, request names 8"
        ):
            harness, outcome, callbacks = self._delete({"20": "9"}, "8", ["20", "21"])
            self._assert_sql_queued_and_committed(harness, outcome, callbacks)

    def test_an_empty_pages_request_is_still_a_value_error_on_a_locked_bid(self):
        harness, outcome, callbacks = self._delete({}, "7", ["", ""])
        self.assertIsInstance(outcome, ValueError)
        self.assertNotIsInstance(outcome, ActiveBidLockedError)
        self.assertEqual(harness.provider.requests, [])


import inspect  # noqa: E402
from pathlib import Path  # noqa: E402
from ost_visualizer.application.dtos.collaboration_dtos import (  # noqa: E402
    MutationRejectionReason as _B2MutationRejectionReason,
)
from ost_visualizer.application.services.base_write_service import (  # noqa: E402
    DatabaseMutationWriteService as _B1DatabaseMutationWriteService,
)
from ost_visualizer.infrastructure.sql.errors import (  # noqa: E402
    SqlInfrastructureError as _B1SqlInfrastructureError,
)
from ost_visualizer.infrastructure.sql.writer import (  # noqa: E402
    SqlProjectWriter as _B1SqlProjectWriter,
)
from tests.helpers.sql.strict_sql_fakes import (
    BidLockState as _B1BidLockState,
)  # noqa: E402
from tests.paths import REPO_ROOT as _B1_REPO_ROOT  # noqa: E402


def _bid_lock_queue_rows():
    """Every queue_* command row (both tables) as (label, results, submit, setup),
    all aimed at the harness database so the client-side Bid guard can see them."""
    rows = [
        (label, results, submit, None)
        for label, results, submit in _queue_rows(_Harness.DATABASE)
    ]
    rows += [
        (row[0], row[1], row[2], row[3]) for row in _plan_queue_rows(_Harness.DATABASE)
    ]
    return rows


def _queued_database_request(label, results, submit, setup, *, locked=False):
    """Queue one command, run its work through the harness executor and return
    (harness, the DatabaseMutationRequest that reached the executor)."""
    harness = _Harness(results)
    harness.data.locked = locked
    if setup:
        setup(harness)
    submit(harness.service, lambda _result: None)
    _queued, execute, _callback = harness.provider.requests[-1]
    execute()
    return harness, (harness.executor.requests or [None])[-1]


class BidLockRejectionPropagationTests(unittest.TestCase):
    """Decision B2: the writer's REJECTED / bid_locked reason survives every service
    result builder (11 MutationExecutionResult sites) on its way to the coordinator.
    Fakes: the executor is the harness fake returning the scripted
    DatabaseMutationResult; the real writer is covered in test_writer."""

    def test_every_queued_command_forwards_the_rejection_reason(self):
        rows = _bid_lock_queue_rows()
        self.assertEqual(len(rows), len(_queue_rows()) + len(_plan_queue_rows()))
        self.assertGreaterEqual(len(rows), 60)
        for label, results, submit, setup in rows:
            with self.subTest(command=label):
                harness = _Harness(results)
                if setup:
                    setup(harness)
                submit(harness.service, lambda _result: None)
                _queued, execute, _callback = harness.provider.requests[-1]
                harness.executor.status = MutationOutcomeStatus.REJECTED
                harness.executor.rejection_reason = (
                    _B2MutationRejectionReason.BID_LOCKED
                )
                execution = execute()
                self.assertEqual(
                    execution.outcome_status, MutationOutcomeStatus.REJECTED
                )
                self.assertIs(
                    execution.rejection_reason, _B2MutationRejectionReason.BID_LOCKED
                )
                self.assertIsNone(execution.authoritative_result)
                self.assertFalse(execution.commit_attempted)

    def test_a_rejection_without_a_reason_and_other_outcomes_carry_none(self):
        for label, results, submit, setup in _bid_lock_queue_rows():
            for status in (
                MutationOutcomeStatus.REJECTED,
                MutationOutcomeStatus.COMMITTED,
                MutationOutcomeStatus.CONFLICT,
            ):
                with self.subTest(command=label, status=status):
                    harness = _Harness(results)
                    if setup:
                        setup(harness)
                    submit(harness.service, lambda _result: None)
                    _queued, execute, _callback = harness.provider.requests[-1]
                    harness.executor.status = status
                    if status is MutationOutcomeStatus.CONFLICT:
                        harness.executor.conflict = _synchronization_conflict()
                    try:
                        execution = execute()
                    except RuntimeError:
                        continue  # a committed run the scripted use case refuses
                    self.assertIsNone(execution.rejection_reason)

    def test_the_synchronous_plan_commands_forward_the_reason_too(self):
        forwarded = 0
        for label, results, command in _plan_local_rows():
            with self.subTest(command=label):
                harness = _Harness(results, sql=False)
                harness.executor.status = MutationOutcomeStatus.REJECTED
                harness.executor.rejection_reason = (
                    _B2MutationRejectionReason.BID_LOCKED
                )
                result = command(harness.service)
                if isinstance(result, MutationExecutionResult):
                    forwarded += 1
                    self.assertEqual(
                        result.outcome_status, MutationOutcomeStatus.REJECTED
                    )
                    self.assertIs(
                        result.rejection_reason, _B2MutationRejectionReason.BID_LOCKED
                    )
        self.assertGreaterEqual(forwarded, 4)

    def test_every_service_result_builder_forwards_the_reason(self):
        # Static pin of the 11 hand-written builders: a new builder that copies
        # the mutation fields must copy the reason as well.
        source = (
            _B1_REPO_ROOT
            / "ost_visualizer"
            / "application"
            / "services"
            / "project_write_service.py"
        ).read_text(encoding="utf-8")
        self.assertEqual(
            source.count("consumed_lock_tokens=mutation.consumed_lock_tokens,"), 11
        )
        self.assertEqual(
            source.count("rejection_reason=mutation.rejection_reason,"), 11
        )

    def test_the_takeoff_placement_guard_rejection_carries_the_bid_locked_reason(self):
        harness = _Harness({"insert_takeoffs": ["101", "102"]})
        harness.data.locked = True
        harness.service.queue_takeoff_placement(
            _Harness.DATABASE,
            "7",
            _plan_specs(),
            "7b3c5ac1-e623-44aa-8203-26a0125873b9",
            lambda _result: None,
        )
        _queued, execute, _callback = harness.provider.requests[-1]
        execution = execute()
        self.assertEqual(execution.outcome_status, MutationOutcomeStatus.REJECTED)
        self.assertIs(execution.rejection_reason, _B2MutationRejectionReason.BID_LOCKED)
        self.assertEqual(harness.calls, [], "a refused placement writes nothing")
        self.assertEqual(harness.executor.requests, [])


class BidLockExemptionContractTests(unittest.TestCase):
    """Decision B1 exemption: only the cleanup of a cancelled takeoff placement may
    delete on a locked Bid, through the dedicated
    queue_cancelled_placement_cleanup_delete. The flag lives on the
    DatabaseMutationRequest, outside the request hash, and no payload can forge it."""

    def _cleanup(self, harness, callback=None):
        return harness.service.queue_cancelled_placement_cleanup_delete(
            _Harness.DATABASE,
            "7",
            ["30"],
            callback or (lambda _result: None),
            page_uids=("20",),
            dependency_resources=(ResourceRef("condition", "10", 7),),
        )

    def test_no_generic_queue_command_sets_the_exemption(self):
        rows = _bid_lock_queue_rows()
        self.assertEqual(len(rows), len(_queue_rows()) + len(_plan_queue_rows()))
        self.assertGreaterEqual(len(rows), 60)
        for label, results, submit, setup in rows:
            for locked in (False, True):
                with self.subTest(command=label, locked=locked):
                    try:
                        _harness, request = _queued_database_request(
                            label, results, submit, setup, locked=locked
                        )
                    except ActiveBidLockedError:
                        continue  # refused at queue time: nothing reaches a writer
                    if request is None:
                        # the placement guard refused it when its work ran
                        self.assertEqual((label, locked), ("placement", True))
                        continue
                    self.assertIs(request.bid_lock_exempt, False)

    def test_the_cleanup_delete_is_queued_on_a_locked_bid_and_only_it_is_exempt(self):
        harness = _Harness()
        harness.data.locked = True
        # the generic delete is refused at queue time for the very same arguments
        with self.assertRaises(ActiveBidLockedError):
            harness.service.queue_plan_items_delete(
                _Harness.DATABASE,
                "7",
                ["30"],
                [],
                lambda _result: None,
                page_uids=("20",),
                dependency_resources=(ResourceRef("condition", "10", 7),),
            )
        self.assertEqual(harness.provider.requests, [])
        self.assertEqual(self._cleanup(harness), 41)
        queued, execute, _callback = harness.provider.requests[-1]
        execution = execute()
        self.assertEqual(execution.outcome_status, MutationOutcomeStatus.COMMITTED)
        request = harness.executor.requests[-1]
        self.assertIs(request.bid_lock_exempt, True)
        self.assertEqual(request.mutation_type, "plan_items_delete")
        self.assertEqual(request.operation_id, queued.operation_id)
        # takeoffs of that one Bid only: never annotations, never another Bid
        self.assertEqual(
            {(r.resource_type, r.bid_uid) for r in queued.resources},
            {("takeoff", 7)},
        )
        self.assertEqual(queued.payload.annotations, ())
        self.assertEqual(queued.payload.takeoff_uids, ("30",))

    def test_the_flag_is_not_part_of_the_request_hash(self):
        harness = _Harness()
        self._cleanup(harness)
        cleanup_request = harness.provider.requests[-1][0]
        other = _Harness()
        other.service.queue_plan_items_delete(
            _Harness.DATABASE,
            "7",
            ["30"],
            [],
            lambda _result: None,
            page_uids=("20",),
            dependency_resources=(ResourceRef("condition", "10", 7),),
        )
        generic_request = other.provider.requests[-1][0]
        self.assertEqual(cleanup_request.request_hash, generic_request.request_hash)
        self.assertEqual(cleanup_request.payload, generic_request.payload)

    def test_a_payload_cannot_forge_the_exemption(self):
        harness = _Harness()
        harness.service.queue_cover_sheet_save(
            _Harness.DATABASE,
            "7",
            {"bid_lock_exempt": True, "notes": "x"},
            lambda _result: None,
        )
        _queued, execute, _callback = harness.provider.requests[-1]
        execute()
        self.assertIs(harness.executor.requests[-1].bid_lock_exempt, False)

    def test_only_the_cleanup_method_sets_the_flag_in_production_code(self):
        offenders = []
        for path in sorted((_B1_REPO_ROOT / "ost_visualizer").rglob("*.py")):
            text = path.read_text(encoding="utf-8")
            if "bid_lock_exempt=True" in text:
                offenders.append(path.relative_to(_B1_REPO_ROOT).as_posix())
        self.assertEqual(
            offenders,
            ["ost_visualizer/application/services/project_write_service.py"],
        )
        source = inspect.getsource(ProjectWriteService)
        self.assertEqual(source.count("bid_lock_exempt=True"), 1)
        self.assertIn(
            "bid_lock_exempt=True",
            inspect.getsource(
                ProjectWriteService.queue_cancelled_placement_cleanup_delete
            ),
        )
        for name in (
            "queue_plan_items_delete",
            "_queue_project_write",
            "queue_takeoff_placement",
        ):
            self.assertNotIn(
                "bid_lock_exempt",
                inspect.signature(getattr(ProjectWriteService, name)).parameters,
                name,
            )
        # the one place a request is built accepts it as an explicit keyword
        self.assertIn(
            "bid_lock_exempt",
            inspect.signature(
                _B1DatabaseMutationWriteService._execute_database_mutation
            ).parameters,
        )


class QueuedResourceShapesVsWriterBidLockRuleTests(unittest.TestCase):
    """Decision B1: the real queue_* commands' DatabaseMutationRequest resources
    fed to the real SqlProjectWriter._validate_mutation_locks with every referenced
    Bid LOCKED. Real: the service request builders, the writer's validation batch
    text and the Python that interprets the answer. Fake: BidLockState evaluates only
    the bid_locked branch on sqlite (see strict_sql_fakes); T-SQL is unverified."""

    # Commands whose resources are tree-level, master data or import: allowed.
    ALLOWED = frozenset(
        {
            "queue_project_create",
            "queue_bid_create",
            "queue_bid_create orphan",
            "queue_project_rename",
            "queue_bids_move",
            "queue_bids_move to orphan",
            "queue_bids_duplicate",
            "queue_bids_delete",
            "queue_projects_delete",
            "queue_bid_job_status_update",
            "queue_condition_types_save",
            "queue_default_layer_insert",
            "queue_default_layers_delete",
            "queue_default_layer_update rename",
            "queue_default_layer_update show",
            "queue_default_layer_update show_all",
            "queue_default_layer_update reorder",
            "queue_job_statuses_save",
            "queue_employees_save",
            "queue_pay_classes_save",
            "queue_project_import",
            "queue_project_import orphan",
        }
    )

    def _refused(self, request):
        resources = set(request.resources) | {
            item.resource for item in request.expected_versions
        }
        state = _B1BidLockState().set_status(1, 1)
        for bid_uid in {r.bid_uid for r in resources if r.bid_uid is not None}:
            state.set_bid(bid_uid, 1)
        try:
            _B1SqlProjectWriter._validate_mutation_locks(
                SimpleNamespace(request=request), state.validation_cursor(), resources
            )
        except _B1SqlInfrastructureError as exc:
            self.assertEqual(str(exc), "The active bid is locked")
            return True
        return False

    def test_the_real_commands_are_refused_or_allowed_by_resource_shape(self):
        rows = _bid_lock_queue_rows()
        actual_allowed = set()
        for label, results, submit, setup in rows:
            with self.subTest(command=label):
                _harness, request = _queued_database_request(
                    label, results, submit, setup
                )
                if not self._refused(request):
                    actual_allowed.add(label)
        self.assertEqual(actual_allowed, set(self.ALLOWED))
        # a new queue_* row must be classified: add it to ALLOWED or to this count
        self.assertEqual(len(rows) - len(actual_allowed), 47)

    def test_every_refused_command_is_also_refused_client_side_except_the_placement(
        self,
    ):
        # Consistency of the two layers on a locked ACTIVE Bid: whatever the writer
        # refuses the queue already refused (placement is refused when its work
        # runs), and the only commands the queue refuses that the writer allows are
        # the Bid moves (user decision Q1 gates the move client-side; the writer
        # exempts moves by resource shape).
        client_refused = set()
        writer_refused = set()
        for label, results, submit, setup in _bid_lock_queue_rows():
            harness = _Harness(results)
            harness.data.locked = True
            if setup:
                setup(harness)
            try:
                submit(harness.service, lambda _result: None)
            except ActiveBidLockedError:
                client_refused.add(label)
            _harness, request = _queued_database_request(label, results, submit, setup)
            if self._refused(request):
                writer_refused.add(label)
        self.assertEqual(writer_refused - client_refused, {"placement"})
        self.assertEqual(
            client_refused - writer_refused,
            {"queue_bids_move", "queue_bids_move to orphan"},
        )


class ClientBidLockRiskTests(unittest.TestCase):
    """Decision B6 (risks 2 and 3) at the client service layer, on a locked or about-to-
    be-locked ACTIVE Bid, with the real ProjectWriteService and its client-side guard:
    duplicating a locked Bid and importing a project are never gated (the duplicate
    only touches Bid-level `bid` resources and the project collection, the import only
    tree-level and master-data resources, and neither carries the writer exemption);
    a Cover Sheet save of an UNLOCKED Bid that changes its status to a locked one is
    queued, not refused (the guard only reads the current flag; the lock re-resolve
    after the commit marks the Bid locked), while the same save on an already locked Bid
    is refused. Fakes: the harness executor and queue provider."""

    LOCKED = True

    def _request(self, label, results, submit, *, locked):
        harness, request = _queued_database_request(
            label, results, submit, None, locked=locked
        )
        return harness, request

    def _row(self, label):
        for row_label, results, submit in _queue_rows(_Harness.DATABASE):
            if row_label == label:
                return results, submit
        raise AssertionError(label)

    def test_a_locked_active_bid_is_duplicated_through_bid_level_resources_only(self):
        results, submit = self._row("queue_bids_duplicate")
        harness, request = self._request(
            "queue_bids_duplicate", results, submit, locked=True
        )
        self.assertIsNotNone(request)
        self.assertEqual(
            {(r.resource_type, r.resource_id) for r in request.resources},
            {("bid", "7"), ("bid", "8"), ("project_bids", "4")},
        )
        self.assertEqual(
            {r.resource_type for r in request.resources if r.bid_uid is not None},
            {"bid"},
        )
        self.assertIs(request.bid_lock_exempt, False)
        self.assertEqual(request.mutation_type, "project_write")
        executed = [
            (name, args)
            for name, _method, args, _kwargs in harness.calls
            if name == "duplicate_bid"
        ]
        self.assertEqual(
            executed,
            [
                ("duplicate_bid", (_Harness.DATABASE, "7")),
                ("duplicate_bid", (_Harness.DATABASE, "8")),
            ],
        )

    def test_the_same_duplicate_is_queued_on_an_unlocked_bid_identically(self):
        results, submit = self._row("queue_bids_duplicate")
        _locked_harness, locked_request = self._request(
            "queue_bids_duplicate", results, submit, locked=True
        )
        _open_harness, open_request = self._request(
            "queue_bids_duplicate", results, submit, locked=False
        )
        self.assertEqual(locked_request.resources, open_request.resources)
        self.assertEqual(locked_request.request_hash, open_request.request_hash)

    def test_an_import_into_a_database_with_a_locked_active_bid_is_not_refused(self):
        for label in ("queue_project_import", "queue_project_import orphan"):
            with self.subTest(command=label):
                results, submit = self._row(label)
                _harness, request = self._request(label, results, submit, locked=True)
                self.assertIsNotNone(request)
                self.assertEqual(request.mutation_type, "project_import")
                self.assertIs(request.bid_lock_exempt, False)
                self.assertTrue(
                    all(resource.bid_uid is None for resource in request.resources),
                    "an import never writes into an existing Bid",
                )

    def test_a_cover_sheet_save_that_flips_an_unlocked_bid_to_a_locked_status_is_queued(
        self,
    ):
        results, submit = self._row("queue_cover_sheet_save")
        harness, request = self._request(
            "queue_cover_sheet_save", results, submit, locked=False
        )
        self.assertIsNotNone(request)
        self.assertIn(
            ("cover_sheet", "7"),
            {(r.resource_type, r.resource_id) for r in request.resources},
        )
        self.assertIs(request.bid_lock_exempt, False)
        # the client does not mark the Bid locked itself: the re-resolve after the
        # commit does
        self.assertIs(harness.data.locked, False)

    def test_the_same_cover_sheet_save_on_an_already_locked_bid_is_refused(self):
        results, submit = self._row("queue_cover_sheet_save")
        with self.assertRaises(ActiveBidLockedError):
            self._request("queue_cover_sheet_save", results, submit, locked=True)


class _ScriptedOutcomeExecutor(_HarnessExecutor):
    """Reports a scripted outcome and value without running the operation: a result
    recovered after an uncertain commit, or one that violates the executor contract."""

    def __init__(self, status, value):
        super().__init__()
        self.scripted_status = status
        self.scripted_value = value

    def execute(self, request, operation):
        self.calls += 1
        self.requests.append(request)
        return DatabaseMutationResult(
            operation_id=request.operation_id,
            outcome_status=self.scripted_status,
            value=self.scripted_value,
        )


class ProjectWriteResultShapeSweepTests(unittest.TestCase):
    """Second-pass mutation sweep of project_write_service.py: result shapes, empty or
    None inputs and guard orders that the golden command tables never reach. Fakes: the
    harness executor, use-case probes and project-data stub (no live Access or SQL
    server)."""

    DATABASE = _Harness.DATABASE

    def test_boolean_resource_helper_reports_exactly_false_for_no_resources(self):
        harness = _Harness()
        ran = []
        result = harness.service._execute_boolean_resource_mutation(
            self.DATABASE,
            (),
            ChangeOperation.UPDATE,
            lambda: ran.append("operation") or True,
        )
        self.assertIs(result, False)
        self.assertEqual((ran, harness.executor.calls), ([], 0))
        controlled = harness.service._execute_boolean_resource_mutation(
            self.DATABASE,
            (ResourceRef("page", "20", 7),),
            ChangeOperation.UPDATE,
            lambda: ran.append("operation") or True,
        )
        self.assertIs(controlled, True)
        self.assertEqual((ran, harness.executor.calls), (["operation"], 1))

    def test_a_falsy_new_uid_is_a_written_result_but_not_a_returned_identity(self):
        # The string-returning wrappers hide a falsy identity (0; an empty string cannot
        # even be recorded as a ResourceRef) as None while the result object still
        # reports the write.
        for label, use_case, wrapper, result_method in (
            (
                "create_project",
                "create_project",
                lambda s: s.create_project(self.DATABASE, "North"),
                lambda s: s.create_project_result(self.DATABASE, "North"),
            ),
            (
                "duplicate_bid",
                "duplicate_bid",
                lambda s: s.duplicate_bid(self.DATABASE, "7"),
                lambda s: s.duplicate_bid_result(self.DATABASE, "7"),
            ),
            (
                "create_bid",
                "create_bid",
                lambda s: s.create_bid(self.DATABASE, "3", {}),
                lambda s: s.create_bid_result(self.DATABASE, "3", {}),
            ),
            (
                "insert_layer",
                "insert_layer",
                lambda s: s.insert_layer(self.DATABASE, "7", "Layer", 1),
                lambda s: s.insert_layer_result(self.DATABASE, "7", "Layer", 1),
            ),
        ):
            with self.subTest(command=label):
                self.assertIsNone(wrapper(_Harness({use_case: 0}).service))
                result = result_method(_Harness({use_case: 0}).service)
                self.assertEqual(
                    (result.value, result.write_success, result.reload_success),
                    (0, True, True),
                )
                self.assertEqual(wrapper(_Harness({use_case: "9"}).service), "9")

    def test_rename_condition_folder_without_a_current_bid_is_refused_before_any_write(
        self,
    ):
        harness = _Harness()
        harness.data.bid_ref = None
        self.assertIs(
            harness.service.rename_condition_folder(self.DATABASE, "f1", "New"), False
        )
        self.assertEqual((harness.calls, harness.executor.calls), ([], 0))
        harness.data.bid_ref = BidRef(self.DATABASE, "7")
        self.assertIs(
            harness.service.rename_condition_folder(self.DATABASE, "f1", "New"), True
        )
        self.assertEqual(
            [(name, method) for name, method, _a, _k in harness.calls],
            [("rename_condition_folder", "execute")],
        )

    def test_none_inputs_mean_no_uids_or_no_changes(self):
        harness = _Harness()
        service = harness.service
        self.assertEqual(
            service.validate_condition_folder_delete(self.DATABASE, "7", None),
            DeleteValidationResult(
                requested_uids=[], blocked_uids=[], failure_reason=None
            ),
        )
        self.assertEqual(
            service.validate_condition_types_delete(self.DATABASE, None),
            DeleteValidationResult(),
        )
        self.assertEqual(
            service.delete_condition_types_result(self.DATABASE, None),
            WriteReloadResult({}, write_success=True, reload_success=True),
        )
        self.assertEqual(
            service.save_condition_types_result(self.DATABASE, None),
            WriteReloadResult({}, write_success=True, reload_success=True),
        )
        self.assertEqual(
            service.save_employees_result(self.DATABASE, None),
            WriteReloadResult({}, write_success=True, reload_success=True),
        )
        self.assertEqual(service.save_job_statuses(self.DATABASE, None), {})
        self.assertEqual(service.save_pay_classes(self.DATABASE, None), {})
        self.assertEqual((harness.calls, harness.executor.calls), ([], 0))

    def test_blocked_folder_delete_reports_the_whole_failure_result(self):
        harness = _Harness()
        harness.data.get_bid_condition_folders = lambda: {
            "f1": BidConditionFolder(uid="f1", name="Walls")
        }
        harness.data.conditions = {
            "10": Condition(
                uid="10", condition_type=Condition.TYPE_LINEAR, folder_uid="f1"
            )
        }
        result = harness.service.delete_condition_folders_result(
            self.DATABASE, "7", ["f1"]
        )
        self.assertEqual(
            result,
            WriteReloadResult(
                None,
                write_success=False,
                reload_success=False,
                failure_reason="condition_folder_in_use",
                blocked_uids=["f1"],
            ),
        )
        self.assertIs(result.refresh_failed, False)
        self.assertEqual((harness.calls, harness.executor.calls), ([], 0))

    def test_folder_usage_walks_every_ancestor_and_ignores_unknown_folders(self):
        harness = _Harness()
        harness.data.get_bid_condition_folders = lambda: {
            "r": BidConditionFolder(uid="r", name="Root"),
            "c": BidConditionFolder(uid="c", name="Child", parent_uid="r"),
            "g": BidConditionFolder(uid="g", name="Grandchild", parent_uid="c"),
        }

        def blocked(condition_folder, requested):
            harness.data.conditions = {
                "10": Condition(
                    uid="10",
                    condition_type=Condition.TYPE_LINEAR,
                    folder_uid=condition_folder,
                )
            }
            return harness.service._condition_folder_uids_in_use(requested)

        # a Condition in the grandchild blocks it and every ancestor up to the root
        self.assertEqual(blocked("g", ["r"]), ["r"])
        self.assertEqual(blocked("g", ["c"]), ["c"])
        self.assertEqual(blocked("g", ["g"]), ["g"])
        self.assertEqual(blocked("g", ["g", "r", "c"]), ["g", "r", "c"])
        # descendants of the Condition's own folder are not affected
        self.assertEqual(blocked("c", ["g"]), [])
        self.assertEqual(blocked("c", ["r", "g"]), ["r"])
        self.assertEqual(blocked("r", ["c", "g"]), [])
        # a Condition without a folder blocks nothing
        self.assertEqual(blocked(None, ["r", "c", "g"]), [])
        self.assertEqual(blocked("", ["r", "c", "g"]), [])
        # a Condition whose folder is not in the folder map blocks nothing, even when
        # that same uid is requested
        self.assertEqual(blocked("zz", ["zz", "r"]), [])

    def test_failure_results_of_the_default_layer_and_area_commands_are_fully_false(
        self,
    ):
        failed = WriteReloadResult(None, write_success=False, reload_success=False)
        harness = _Harness()
        harness.service._connection_manager = SimpleNamespace(
            is_write_blocked=lambda: True
        )
        self.assertEqual(
            harness.service.insert_default_layer_result(self.DATABASE, "D", 1), failed
        )
        self.assertEqual((harness.calls, harness.executor.calls), ([], 0))
        # an area save whose use case returns no identity for a new Area
        harness = _Harness({"save_bid_areas": {}})
        result = harness.service.save_bid_areas_result(
            self.DATABASE,
            "7",
            BidAreaChangeset(
                new=[
                    BidArea(
                        uid="new_0", bid_uid="7", parent_uid="0", name="N", sequence=1
                    )
                ],
                updated=[],
                deleted_uids=[],
            ),
        )
        self.assertEqual(result, failed)
        self.assertIs(result.refresh_failed, False)
        self.assertEqual(harness.reloads, [])

    def test_default_layer_commands_do_nothing_while_writes_are_blocked(self):
        harness = _Harness()
        harness.service._connection_manager = SimpleNamespace(
            is_write_blocked=lambda: True
        )
        service = harness.service
        self.assertIs(
            service.swap_default_layer_sequence(self.DATABASE, "1", "2"), False
        )
        self.assertIs(
            service.update_default_layer_name(self.DATABASE, "1", "Renamed"), False
        )
        self.assertIs(
            service.update_default_layer_show(self.DATABASE, "1", True), False
        )
        result = service.delete_default_layers(self.DATABASE, ["1", "2", "1", ""])
        self.assertEqual(
            (
                result.requested_uids,
                result.succeeded_uids,
                result.failed_uids,
                result.reload_success,
            ),
            (["1", "2"], [], ["1", "2"], True),
        )
        self.assertIs(result.success, False)
        self.assertEqual((harness.calls, harness.executor.calls), ([], 0))
        self.assertEqual(harness.reloads, [])
        # the same commands reach their use cases once writes are allowed
        service._connection_manager = SimpleNamespace(is_write_blocked=lambda: False)
        self.assertIs(
            service.swap_default_layer_sequence(self.DATABASE, "1", "2"), True
        )
        self.assertIs(service.update_default_layer_name(self.DATABASE, "1", "R"), True)
        self.assertIs(service.update_default_layer_show(self.DATABASE, "1", True), True)
        self.assertTrue(service.delete_default_layers(self.DATABASE, ["1"]).success)
        self.assertEqual(
            [(name, method) for name, method, _a, _k in harness.calls],
            [
                ("swap_layer_sequence", "execute_default"),
                ("update_layer_name", "execute_default"),
                ("update_layer_show", "execute_default"),
                ("delete_layer", "execute_default"),
            ],
        )

    def test_employee_and_condition_type_saves_judge_the_use_case_result_exactly(self):
        changes = {"new": [{"uid": "n1"}], "updated": [], "deleted_uids": []}
        for label, use_case, command in (
            (
                "employees",
                "save_employees",
                lambda s: s.save_employees_result(self.DATABASE, changes),
            ),
            (
                "condition types",
                "save_condition_types",
                lambda s: s.save_condition_types_result(self.DATABASE, changes),
            ),
        ):
            for value, recorded, success, expected_value in (
                (False, 0, False, None),
                (None, 0, False, None),
                (True, 1, True, {} if label == "employees" else True),
                ({"n1": "e9"}, 1, True, {"n1": "e9"}),
                ({}, 1, True, {}),
            ):
                with self.subTest(command=label, use_case_result=value):
                    harness = _Harness({use_case: value})
                    result = command(harness.service)
                    self.assertIs(result.write_success, success)
                    self.assertEqual(result.value, expected_value)
                    self.assertEqual(
                        len(harness.executor.recorder.changes),
                        recorded,
                    )
                    self.assertEqual(
                        harness.reloads, [self.DATABASE] if success else []
                    )

    def test_condition_type_save_publishes_the_catalog_change_only_for_the_active_bid_of_that_database(
        self,
    ):
        changes = {"new": [{"uid": "n1"}], "updated": [], "deleted_uids": []}

        def published(active):
            harness = _Harness({"save_condition_types": {"n1": "t9"}})
            harness.data.bid_ref = active
            result = harness.service.save_condition_types_result(self.DATABASE, changes)
            self.assertIs(result.success, True)
            return [
                (event.__name__, payload.get("bid_uid"))
                for event, payload in harness.events.published
            ]

        self.assertEqual(
            published(BidRef(self.DATABASE, "7")),
            [("ConditionsChangedEvent", "7")],
        )
        self.assertEqual(published(None), [])
        self.assertEqual(published(BidRef("C:/jobs/other.mdb", "7")), [])

    def test_condition_type_usage_failures_are_logged_and_unavailable(self):
        harness = _Harness()
        service = harness.service
        service._condition_type_uids_in_use_provider = None
        with self.assertLogs("test.project_write_harness", level="WARNING") as logged:
            self.assertIsNone(service._condition_type_uids_in_use(self.DATABASE))
        self.assertEqual(
            [(r.levelname, r.getMessage(), r.exc_info) for r in logged.records],
            [
                (
                    "WARNING",
                    "Cannot validate condition type usage without a provider",
                    None,
                )
            ],
        )

        def failing(_database_id):
            raise RuntimeError("usage query failed")

        service._condition_type_uids_in_use_provider = failing
        with self.assertLogs("test.project_write_harness", level="WARNING") as logged:
            self.assertIsNone(service._condition_type_uids_in_use(self.DATABASE))
        self.assertEqual(len(logged.records), 1)
        self.assertEqual(
            logged.records[0].getMessage(),
            "Failed to validate condition type usage before delete",
        )
        self.assertEqual(logged.records[0].exc_info[0], RuntimeError)
        service._condition_type_uids_in_use_provider = lambda _db: {1, None, "2"}
        self.assertEqual(service._condition_type_uids_in_use(self.DATABASE), {"1", "2"})


class ProjectWriteCommittedWithoutValueSweepTests(unittest.TestCase):
    """A COMMITTED outcome that carries no value (a result recovered after an uncertain
    commit, or an executor that breaks the contract) must not crash the command. A value
    on a non-committed outcome cannot exist: DatabaseMutationResult refuses it, so the
    `status == COMMITTED and value` guards of the paste commands are redundant for that
    half. Fake: a scripted executor that never runs the operation."""

    DATABASE = _Harness.DATABASE

    @staticmethod
    def _scripted(harness, status, value):
        harness.service._mutation_executor = _ScriptedOutcomeExecutor(status, value)
        return harness.service._mutation_executor

    def test_committed_takeoff_insert_without_a_value_is_an_empty_unrefreshed_success(
        self,
    ):
        harness = _Harness()
        self._scripted(harness, MutationOutcomeStatus.COMMITTED, None)
        result = harness.service.insert_takeoffs_result(
            self.DATABASE, "7", _plan_specs()
        )
        self.assertEqual(
            result, WriteReloadResult([], write_success=True, reload_success=True)
        )
        self.assertEqual((harness.reloads, harness.events.published), ([], []))
        self.assertEqual(
            harness.service.insert_takeoffs(self.DATABASE, "7", _plan_specs()), []
        )

    def test_committed_queued_placement_without_a_value_reports_an_incomplete_identity_set(
        self,
    ):
        harness = _Harness()
        self._scripted(harness, MutationOutcomeStatus.COMMITTED, None)
        harness.service.queue_takeoff_placement(
            self.DATABASE, "7", _plan_specs(), str(uuid.uuid4()), lambda _r: None
        )
        _request, execute, _callback = harness.provider.requests[-1]
        result = execute()
        self.assertEqual(result.outcome_status, MutationOutcomeStatus.COMMITTED)
        self.assertEqual(result.created_resource_ids, ())
        self.assertEqual(
            result.authoritative_result.created_uid_maps, (("takeoffs", ()),)
        )
        validator = harness.provider.options[-1]["result_validator"]
        self.assertEqual(
            validator(result),
            "The SQL mutation returned an incomplete authoritative identity set.",
        )

    def test_paste_results_survive_a_committed_outcome_without_a_value(self):
        payload = MdbSqlBehaviorParityTests._mixed_paste_payload()
        empty_maps = (("takeoffs", ()), ("annotations", ()), ("conditions", ()))
        for label, status, committed in (
            ("committed without value", MutationOutcomeStatus.COMMITTED, True),
            ("rejected", MutationOutcomeStatus.REJECTED, False),
            ("failed before commit", MutationOutcomeStatus.FAILED_BEFORE_COMMIT, False),
        ):
            with self.subTest(case=label, route="queued"):
                harness = _Harness()
                self._scripted(harness, status, None)
                harness.service.queue_plan_items_paste(
                    self.DATABASE, payload, lambda _r: None
                )
                _request, execute, _callback = harness.provider.requests[-1]
                result = execute()
                self.assertEqual(result.outcome_status, status)
                self.assertEqual(result.created_resource_ids, ())
                if committed:
                    self.assertEqual(
                        result.authoritative_result.created_uid_maps, empty_maps
                    )
                    self.assertEqual(
                        harness.provider.options[-1]["result_validator"](result),
                        "The paste returned an incomplete authoritative UID set.",
                    )
                else:
                    self.assertIsNone(result.authoritative_result)
            with self.subTest(case=label, route="local"):
                harness = _Harness(sql=False)
                self._scripted(harness, status, None)
                result = harness.service.execute_plan_items_paste_local(
                    self.DATABASE, payload
                )
                self.assertEqual(result.outcome_status, status)
                self.assertEqual(result.created_resource_ids, ())
                if committed:
                    self.assertEqual(
                        result.authoritative_result.created_uid_maps, empty_maps
                    )
                    self.assertEqual(harness.reloads, [self.DATABASE])
                else:
                    self.assertIsNone(result.authoritative_result)
                    self.assertEqual(harness.reloads, [])

    def test_committed_scale_batch_without_a_value_saves_nothing_and_does_not_refresh(
        self,
    ):
        harness = _Harness()
        self._scripted(harness, MutationOutcomeStatus.COMMITTED, None)
        self.assertIs(
            harness.service.save_page_scales(self.DATABASE, ["20", "21"], 1.0, 96.0),
            False,
        )
        self.assertEqual((harness.reloads, harness.events.published), ([], []))
        # positive control: a committed (any, all) pair is judged by its flags
        harness = _Harness()
        self._scripted(harness, MutationOutcomeStatus.COMMITTED, (True, True))
        self.assertIs(
            harness.service.save_page_scales(self.DATABASE, ["20", "21"], 1.0, 96.0),
            True,
        )
        self.assertEqual(harness.reloads, [self.DATABASE])


class ProjectWritePageProjectionSweepTests(unittest.TestCase):
    """save_page_name and save_page_scales project into the loaded Bid in place when the
    page is known and fall back to a reload otherwise. Fake: the harness project-data
    stub, whose apply_* methods are replaced by recording fakes."""

    DATABASE = _Harness.DATABASE

    def _harness(self, applied, *, reload_result=True, known=("20",)):
        harness = _Harness(reload_result=reload_result)
        for uid in known:
            harness.data.pages[uid] = Page(uid=uid, name=f"Sheet {uid}")
        calls = []

        def apply_page_name(bid_ref, page, name):
            calls.append(("name", bid_ref, page.uid, name))
            return applied

        harness.data.apply_page_name = apply_page_name
        harness.apply_calls = calls
        return harness

    def test_a_projected_page_rename_publishes_page_metadata_without_reloading(self):
        harness = self._harness(True)
        self.assertIs(harness.service.save_page_name(self.DATABASE, "20", "New"), True)
        self.assertEqual(
            harness.apply_calls,
            [("name", BidRef(self.DATABASE, "7"), "20", "New")],
        )
        self.assertEqual(
            [(event.__name__, payload) for event, payload in harness.events.published],
            [
                (
                    "PageMetadataChangedEvent",
                    {
                        "database_id": self.DATABASE,
                        "bid_uid": "7",
                        "page_uids": ("20",),
                        "changed_fields": ("name",),
                    },
                )
            ],
        )
        self.assertEqual(harness.reloads, [])

    def test_a_refused_projection_or_unknown_page_falls_back_to_a_reload(self):
        for label, applied, known in (
            ("projection refused", False, ("20",)),
            ("page unknown", True, ()),
        ):
            for reload_ok in (True, False):
                with self.subTest(case=label, reload_ok=reload_ok):
                    harness = self._harness(
                        applied, reload_result=reload_ok, known=known
                    )
                    self.assertIs(
                        harness.service.save_page_name(self.DATABASE, "20", "New"),
                        reload_ok,
                    )
                    self.assertEqual(harness.reloads, [self.DATABASE])
                    self.assertEqual(
                        [event.__name__ for event, _p in harness.events.published],
                        ["DatabaseRefreshedEvent"] if reload_ok else [],
                    )
                    if reload_ok:
                        payload = harness.events.published[0][1]
                        self.assertIs(payload["image_sources_unchanged"], True)
                        self.assertIs(payload["mesh_scene_unchanged"], True)
                    self.assertEqual(len(harness.apply_calls), 1 if known else 0)

    def test_a_scale_batch_is_complete_only_when_every_page_saved(self):
        harness = _Harness({"save_page_scale": _Seq(False, True)})
        harness.data.pages = {
            "20": Page(uid="20", name="A"),
            "21": Page(uid="21", name="B"),
        }
        self.assertIs(
            harness.service.save_page_scales(self.DATABASE, ["20", "21"], 1.0, 96.0),
            False,
        )
        harness = _Harness({"save_page_scale": _Seq(True, False)})
        harness.data.pages = {
            "20": Page(uid="20", name="A"),
            "21": Page(uid="21", name="B"),
        }
        self.assertIs(
            harness.service.save_page_scales(self.DATABASE, ["20", "21"], 1.0, 96.0),
            False,
        )
        harness = _Harness({"save_page_scale": True})
        harness.data.pages = {
            "20": Page(uid="20", name="A"),
            "21": Page(uid="21", name="B"),
        }
        self.assertIs(
            harness.service.save_page_scales(self.DATABASE, ["20", "21"], 1.0, 96.0),
            True,
        )

    def test_a_scale_batch_with_an_unknown_saved_page_refreshes_instead_of_projecting(
        self,
    ):
        harness = _Harness()
        harness.data.pages = {"20": Page(uid="20", name="A")}
        projected = []
        harness.data.apply_page_scales = lambda *args: projected.append(args) or ()
        self.assertIs(
            harness.service.save_page_scales(self.DATABASE, ["20", "21"], 1.0, 96.0),
            True,
        )
        self.assertEqual(projected, [])
        self.assertEqual(harness.reloads, [self.DATABASE])
        event, payload = harness.events.published[-1]
        self.assertEqual(event.__name__, "DatabaseRefreshedEvent")
        self.assertEqual(payload["page_scale_uids"], ("20", "21"))
        # control: every saved page known -> projected in place, no reload
        harness = _Harness()
        harness.data.pages = {
            "20": Page(uid="20", name="A"),
            "21": Page(uid="21", name="B"),
        }
        projected = []
        harness.data.apply_page_scales = lambda *args: (
            projected.append(args) or ("20", "21")
        )
        self.assertIs(
            harness.service.save_page_scales(self.DATABASE, ["20", "21"], 1.0, 96.0),
            True,
        )
        self.assertEqual(len(projected), 1)
        self.assertEqual([page.uid for page in projected[0][1]], ["20", "21"])
        self.assertEqual(harness.reloads, [])
        self.assertEqual(
            [event.__name__ for event, _p in harness.events.published],
            ["PageMetadataChangedEvent"],
        )

    def test_queued_page_setting_reports_a_zero_sequence_as_queued(self):
        for sequence, expected in ((-1, False), (0, True), (1, True), (41, True)):
            with self.subTest(sequence=sequence):
                harness = _Harness()
                harness.provider.queue_request = lambda *_a, _s=sequence, **_k: _s
                self.assertIs(
                    harness.service.queue_page_setting_if_sql(
                        self.DATABASE, "20", "show_mode", [2]
                    ),
                    expected,
                )


class ProjectWritePlanInputSweepTests(unittest.TestCase):
    """Plan commands: identity sets, sentinels, ownership capture, geometry families,
    property and page-setting update filters, paste hierarchy. Where an input is outside
    the documented domain (an update entry without a uid) the test pins the CURRENT
    behaviour, named as such: those commands do not validate their updates up front.
    Fakes: the harness executor, use-case probes, queue provider and project-data
    stub."""

    DATABASE = _Harness.DATABASE

    @staticmethod
    def _spec(parent_uid=None, **overrides):
        values = dict(
            condition_uid="10",
            page_uid="20",
            area_uid="0",
            position=[0.0, 0.0],
            parent_uid=parent_uid,
        )
        values.update(overrides)
        return InsertTakeoffSpec(**values)

    def test_takeoff_insert_identity_set_must_be_complete_unique_and_non_empty(self):
        specs = [self._spec(), self._spec()]
        for label, returned in (
            ("none", None),
            ("empty", []),
            ("short", ["5"]),
            ("duplicate", ["5", "5"]),
            ("blank identity", ["5", ""]),
            ("none entry", ["5", None]),
        ):
            with self.subTest(returned=label):
                harness = _Harness({"insert_takeoffs": returned})
                with self.assertRaisesRegex(
                    RuntimeError, "incomplete authoritative identity set"
                ):
                    harness.service.insert_takeoffs_result(self.DATABASE, "7", specs)
                self.assertEqual(harness.executor.recorder.changes, [])
        harness = _Harness({"insert_takeoffs": ["5", "6"]})
        result = harness.service.insert_takeoffs_result(self.DATABASE, "7", specs)
        self.assertEqual(
            (result.value, result.write_success, result.reload_success),
            (["5", "6"], True, True),
        )

    def test_placement_depends_on_a_parent_takeoff_only_for_a_real_parent_uid(self):
        specs = [self._spec(parent_uid) for parent_uid in (None, "", 0, "0", 1, "30")]
        harness = _Harness()
        harness.service.queue_takeoff_placement(
            self.DATABASE, "7", specs, str(uuid.uuid4()), lambda _r: None
        )
        request = harness.provider.requests[-1][0]
        self.assertEqual(
            request.dependency_resources,
            tuple(
                sorted(
                    {
                        ResourceRef("page", "20", 7),
                        ResourceRef("condition", "10", 7),
                        ResourceRef("takeoff", "1", 7),
                        ResourceRef("takeoff", "30", 7),
                    }
                )
            ),
        )

    def test_takeoff_reassignment_check_returns_exactly_false_for_each_refusal(self):
        def check(harness, database=self.DATABASE, uids=("30",), condition="10"):
            return harness.service._can_reassign_takeoffs_condition(
                database, list(uids), condition
            )

        harness = _Harness()
        self.assertIs(check(harness), True)
        self.assertIs(check(harness, database="C:/jobs/other.mdb"), False)
        self.assertIs(check(harness, uids=("30", "99")), False)
        harness.data.conditions["11"] = Condition(
            uid="11", condition_type=Condition.TYPE_COUNT
        )
        self.assertIs(check(harness, condition="11"), False)
        harness.data.bid_ref = None
        self.assertIs(check(harness), False)

    def test_geometry_families_follow_the_kinds_of_item_moved(self):
        for label, kwargs, families in (
            ("positions only", {"takeoff_positions": [("30", [1, 2])]}, ("takeoffs",)),
            ("rotations only", {"takeoff_rotations": [("30", 90)]}, ("takeoffs",)),
            (
                "annotation positions only",
                {"annotation_positions": [("a1", "rect", [1, 2, 3, 4])]},
                ("annotations",),
            ),
            (
                "positions and annotations",
                {
                    "takeoff_positions": [("30", [1, 2])],
                    "annotation_positions": [("a1", "rect", [1, 2, 3, 4])],
                },
                ("takeoffs", "annotations"),
            ),
        ):
            with self.subTest(case=label, route="local"):
                harness = _Harness(sql=False)
                result = harness.service.execute_plan_geometry_local(
                    self.DATABASE,
                    "7",
                    publish_database_refreshed_after_write=False,
                    **kwargs,
                )
                self.assertEqual(result.outcome_status, MutationOutcomeStatus.COMMITTED)
                self.assertEqual(
                    result.authoritative_result.affected_families, families
                )
            with self.subTest(case=label, route="queued"):
                harness = _Harness()
                harness.service.queue_plan_geometry(
                    self.DATABASE, "7", lambda _r: None, **kwargs
                )
                _request, execute, _callback = harness.provider.requests[-1]
                result = execute()
                self.assertEqual(result.outcome_status, MutationOutcomeStatus.COMMITTED)
                self.assertEqual(
                    result.authoritative_result.affected_families, families
                )

    def test_takeoff_ownership_capture_normalizes_root_parent_and_unassigned_area(self):
        harness = _Harness()
        harness.data.takeoffs = [
            Takeoff(
                uid="30",
                page_uid="20",
                condition_uid="10",
                area_uid="5",
                parent_uid="0",
            ),
            Takeoff(
                uid="31",
                page_uid="20",
                condition_uid="10",
                area_uid="",
                parent_uid="30",
            ),
            Takeoff(
                uid="32",
                page_uid="21",
                condition_uid="11",
                area_uid=None,
                parent_uid="",
            ),
            Takeoff(
                uid="33",
                page_uid="21",
                condition_uid="11",
                area_uid="0",
                parent_uid=None,
            ),
        ]
        captured = harness.service._capture_plan_takeoff_ownership(
            self.DATABASE, "7", ("30", "32", "33")
        )
        self.assertEqual(
            [
                (
                    item.uid,
                    item.page_uid,
                    item.condition_uid,
                    item.area_uid,
                    item.parent_uid,
                )
                for item in captured
            ],
            [
                ("30", "20", "10", "5", "0"),
                ("31", "20", "10", "0", "30"),
                ("32", "21", "11", "0", "0"),
                ("33", "21", "11", "0", "0"),
            ],
        )

    def test_takeoff_ownership_capture_requires_the_current_bid_and_known_takeoffs(
        self,
    ):
        for label, setup, message in (
            (
                "no current bid",
                lambda h: setattr(h.data, "bid_ref", None),
                "no longer owns",
            ),
            (
                "other database",
                lambda h: setattr(h.data, "bid_ref", BidRef("C:/jobs/other.mdb", "7")),
                "no longer owns",
            ),
            (
                "other bid",
                lambda h: setattr(h.data, "bid_ref", BidRef(self.DATABASE, "8")),
                "no longer owns",
            ),
            ("unknown takeoff", lambda h: None, "no longer authoritative"),
        ):
            with self.subTest(case=label):
                harness = _Harness(sql=False)
                setup(harness)
                uids = ("30", "99") if label == "unknown takeoff" else ("30",)
                with self.assertRaisesRegex(ValueError, message):
                    harness.service._capture_plan_takeoff_ownership(
                        self.DATABASE, "7", uids
                    )
                if label == "unknown takeoff":
                    continue
                result = harness.service.execute_plan_properties_local(
                    self.DATABASE, "7", "takeoff_text", [("30", {"Text": "T"})]
                )
                self.assertEqual(
                    result.outcome_status, MutationOutcomeStatus.FAILED_BEFORE_COMMIT
                )
                self.assertIn(
                    "The property mutation no longer owns the current Bid.",
                    result.message,
                )
                self.assertEqual(harness.executor.calls, 0)

    def test_local_annotation_property_batches_track_only_resources_with_a_uid(self):
        # PINS CURRENT BEHAVIOUR for malformed entries (no up-front validation): an entry
        # without a uid is still applied by the use case but adds no resource.
        harness = _Harness(sql=False)
        result = harness.service.execute_plan_properties_local(
            self.DATABASE,
            "7",
            "annotation_text",
            [("a1", "rect", {"Text": "T"}), ("", "rect", {"Text": "U"})],
            publish_database_refreshed_after_write=False,
        )
        self.assertEqual(result.outcome_status, MutationOutcomeStatus.COMMITTED)
        self.assertEqual(
            result.authoritative_result.updated_resources,
            (ResourceRef("annotation", "rect/a1", 7),),
        )
        applied = [
            args
            for name, _m, args, _k in harness.calls
            if name == "save_annotation_text_properties"
        ]
        self.assertEqual(
            applied,
            [
                (
                    self.DATABASE,
                    [("a1", "rect", {"Text": "T"}), ("", "rect", {"Text": "U"})],
                )
            ],
        )

    def test_local_annotation_property_batch_with_an_empty_entry_fails_inside_the_transaction(
        self,
    ):
        # PINS CURRENT BEHAVIOUR: an empty update entry raises IndexError from the
        # operation (after the executor was entered); it is not rejected up front.
        harness = _Harness(sql=False)
        with self.assertRaises(IndexError):
            harness.service.execute_plan_properties_local(
                self.DATABASE,
                "7",
                "annotation_text",
                [("a1", "rect", {"Text": "T"}), ()],
            )
        self.assertEqual(harness.executor.calls, 1)
        self.assertEqual(harness.executor.recorder.changes, [])

    def test_queued_annotation_property_resources_need_a_uid_a_type_and_nothing_else(
        self,
    ):
        harness = _Harness()
        harness.service.queue_plan_properties(
            self.DATABASE,
            "7",
            "annotation_text",
            [
                ("a1", "rect", {"Text": "T"}),
                ("", "rect", {"Text": "no uid"}),
                ("a2", "", {"Text": "no type"}),
                ("a3", "rect"),
                ("a4", "rect", {}),
            ],
            lambda _r: None,
        )
        request = harness.provider.requests[-1][0]
        self.assertEqual(
            request.resources,
            tuple(
                sorted(
                    ResourceRef("annotation", f"rect/{uid}", 7)
                    for uid in ("a1", "a3", "a4")
                )
            ),
        )

    def test_queued_takeoff_property_resources_skip_a_falsy_uid_but_keep_its_ownership(
        self,
    ):
        # PINS CURRENT BEHAVIOUR: a Takeoff whose uid is "0" (outside the autonumber
        # domain) is filtered from the update resources like any falsy uid, while its
        # ownership dependency is still captured.
        harness = _Harness()
        harness.tokens.guard = True
        harness.data.takeoffs = [
            Takeoff(uid="30", page_uid="20", condition_uid="10", parent_uid=""),
            Takeoff(uid="31", page_uid="20", condition_uid="10", parent_uid="30"),
            Takeoff(uid="0", page_uid="20", condition_uid="10", parent_uid="30"),
        ]
        harness.service.queue_plan_properties(
            self.DATABASE,
            "7",
            "takeoff_text",
            [("30", {"Text": "T"}), (0, {"Text": "U"})],
            lambda _r: None,
        )
        request = harness.provider.requests[-1][0]
        self.assertEqual(request.resources, (ResourceRef("takeoff", "30", 7),))
        self.assertEqual(
            {r.resource_id for r in request.dependency_resources},
            {"0", "30", "31"},
        )

    def test_queued_property_concurrency_guard_skips_only_the_unassigned_area(self):
        harness = _Harness()
        harness.tokens.guard = True
        harness.service.queue_plan_properties(
            self.DATABASE,
            "7",
            "takeoff_condition",
            [("30", "10")],
            lambda _r: None,
            dependency_resources=(
                ResourceRef("area", "0", 7),
                ResourceRef("area", "5", 7),
                ResourceRef("layer", "0", 7),
            ),
        )
        _database, guarded = harness.tokens.expected_requests[-1]
        self.assertEqual(
            set(guarded),
            {
                ResourceRef("takeoff", "30", 7),
                ResourceRef("takeoff", "31", 7),
                ResourceRef("area", "5", 7),
                ResourceRef("layer", "0", 7),
            },
        )

    def test_queued_page_setting_resources_skip_entries_without_a_uid(self):
        # PINS CURRENT BEHAVIOUR for malformed entries: they contribute no resource.
        for kind, good, bad, resource_type, ids in (
            (
                "scale",
                [["20", 1, 96.5], ["21", 1, 96.5], ["20", 1, 96.5]],
                [[], ["", 1, 96.5]],
                "page",
                ("20", "21"),
            ),
            (
                "layer_show",
                [["40", 0], ["41", 1]],
                [[], ["", 1]],
                "layer",
                ("40", "41"),
            ),
        ):
            with self.subTest(kind=kind):
                harness = _Harness()
                harness.service.queue_page_settings(
                    self.DATABASE,
                    "7",
                    kind,
                    [good[0], *bad, *good[1:]],
                    lambda _r: None,
                )
                request = harness.provider.requests[-1][0]
                self.assertEqual(
                    request.resources,
                    tuple(ResourceRef(resource_type, uid, 7) for uid in ids),
                )

    def test_a_queued_multi_page_setting_fails_unless_every_page_saves(self):
        for kind, use_case, updates in (
            ("scale", "save_page_scale", [["20", 1, 96.5], ["21", 1, 96.5]]),
            ("show_mode", "save_page_show_mode", [["20", 2], ["21", 3]]),
            (
                "overlay_image",
                "save_page_overlay_image",
                [["20", "C:/a.png"], ["21", "C:/b.png"]],
            ),
            (
                "overlay_rect",
                "save_page_overlay_rect",
                [["20", [1, 2, 3, 4]], ["21", [1, 2, 3, 4]]],
            ),
            ("invert", "save_page_invert", [["20", 1], ["21", 0]]),
            ("bitonal", "save_page_bitonal", [["20", 1], ["21", 0]]),
            ("area", "save_page_area", [["20", "5"], ["21", "6"]]),
            ("name", "save_page_name", [["20", "A"], ["21", "B"]]),
            ("layer_show", "update_layer_show", [["40", 0], ["41", 1]]),
        ):
            with self.subTest(kind=kind):
                harness = _Harness({use_case: _Seq(True, False)})
                harness.service.queue_page_settings(
                    self.DATABASE, "7", kind, updates, lambda _r: None
                )
                _request, execute, _callback = harness.provider.requests[-1]
                with self.assertRaisesRegex(
                    RuntimeError, "The page setting update was incomplete."
                ):
                    execute()
                self.assertEqual(len(harness.calls), 2)
                self.assertEqual(harness.executor.recorder.changes, [])
                harness = _Harness({use_case: True})
                harness.service.queue_page_settings(
                    self.DATABASE, "7", kind, updates, lambda _r: None
                )
                _request, execute, _callback = harness.provider.requests[-1]
                self.assertEqual(
                    execute().outcome_status, MutationOutcomeStatus.COMMITTED
                )

    def test_queued_plan_property_batches_fail_unless_every_group_saves(self):
        for kind, use_case, updates in (
            ("takeoff_area", "save_takeoffs_area", [("30", "5"), ("32", "6")]),
            (
                "takeoff_condition",
                "save_takeoffs_condition",
                [("30", "10"), ("32", "11")],
            ),
            (
                "takeoff_negative",
                "set_takeoffs_negative",
                [("30", True), ("32", False)],
            ),
            (
                "takeoff_curve",
                "set_takeoff_curve",
                [("30", [1, 2], 3), ("32", [1, 2], 4)],
            ),
        ):
            with self.subTest(kind=kind):
                harness = _Harness({use_case: _Seq(True, False)})
                harness.tokens.guard = True
                harness.service.queue_plan_properties(
                    self.DATABASE, "7", kind, updates, lambda _r: None
                )
                _request, execute, _callback = harness.provider.requests[-1]
                with self.assertRaisesRegex(
                    RuntimeError, "The plan property update was incomplete."
                ):
                    execute()
                self.assertEqual(len(harness.calls), 2)

    def _hierarchy(self, sources, parents, external=()):
        batches = []

        def insert(_database, _bid, specs):
            batches.append([spec.parent_uid for spec in specs])
            return [f"n{len(batches)}_{index}" for index in range(len(specs))]

        harness = _Harness({"insert_takeoffs": insert}, sql=False)
        payload = SimpleNamespace(
            destination_bid_uid="7",
            takeoff_source_uids=tuple(sources),
            takeoff_external_parent_sources=tuple(external),
        )
        specs = tuple(self._spec(parent) for parent in parents)
        mapping = harness.service._insert_pasted_takeoff_hierarchy(
            self.DATABASE, payload, specs
        )
        return mapping, batches

    def test_paste_hierarchy_requires_one_unique_source_per_takeoff(self):
        for label, sources, parents in (
            ("fewer sources than specs", ("a",), (None, None)),
            ("more sources than specs", ("a", "b"), (None,)),
            ("duplicate sources", ("a", "a"), (None, None)),
        ):
            with self.subTest(case=label):
                with self.assertRaisesRegex(
                    ValueError, "one unique source UID per Takeoff"
                ):
                    self._hierarchy(sources, parents)
        mapping, batches = self._hierarchy(("a", "b"), (None, None))
        self.assertEqual(
            (mapping, batches), ({"a": "n1_0", "b": "n1_1"}, [[None, None]])
        )

    def test_paste_hierarchy_resolves_only_parents_inside_the_paste(self):
        # a parent inside the paste is remapped to its new uid and inserted later
        mapping, batches = self._hierarchy(("a", "b"), (None, "a"))
        self.assertEqual(
            (mapping, batches),
            ({"a": "n1_0", "b": "n2_0"}, [[None], ["n1_0"]]),
        )
        # a parent outside the paste keeps its (existing) uid in the first batch
        mapping, batches = self._hierarchy(("a", "b"), (None, "99"))
        self.assertEqual(
            (mapping, batches), ({"a": "n1_0", "b": "n1_1"}, [[None, "99"]])
        )
        # a parent bound as an existing parent stays the existing uid even when the same
        # uid is also being pasted
        mapping, batches = self._hierarchy(("a", "b"), (None, "a"), external=("b",))
        self.assertEqual(
            (mapping, batches), ({"a": "n1_0", "b": "n1_1"}, [[None, "a"]])
        )
        # root-parent sentinels are never parents, even when a pasted source is named like one
        for source, parent in (("0", "0"), ("None", "None"), ("", "")):
            with self.subTest(source=source, parent=parent):
                _mapping, batches = self._hierarchy((source, "b"), (None, parent))
                self.assertEqual(batches, [[None, parent]])
        with self.assertRaisesRegex(ValueError, "parent cycle"):
            self._hierarchy(("a", "b"), ("b", "a"))

    def test_paste_named_view_dependencies_skip_empty_targets_and_copied_views(self):
        payload = SimpleNamespace(
            annotation_source_uids=(
                "namedview/5",
                *(f"hotlink/h{index}" for index in range(7)),
            ),
            annotation_specs=(
                InsertAnnotationSpec(
                    page_uid="p1",
                    annotation_type="namedview",
                    position=[0.0, 0.0, 1.0, 1.0],
                    color="#000000",
                    width=1.0,
                ),
                *(
                    InsertAnnotationSpec(
                        page_uid="p1",
                        annotation_type="hotlink",
                        position=[0.0, 0.0, 1.0, 1.0],
                        color="#000000",
                        width=1.0,
                        properties={"BidPageViewUID": target},
                    )
                    for target in (None, "", 0, "0", 1, "5", "7")
                ),
            ),
        )
        self.assertEqual(
            ProjectWriteService._plan_paste_named_view_dependencies(payload, 7),
            {
                ResourceRef("annotation", "namedview/1", 7),
                ResourceRef("annotation", "namedview/7", 7),
            },
        )

    @staticmethod
    def _annotation_only_paste(source="6", destination="7"):
        return PlanItemsPastePayload(
            source_bid_uid=source,
            destination_bid_uid=destination,
            annotation_source_uids=(annotation_resource_id("rect", "a1"),),
            annotation_specs=(
                InsertAnnotationSpec(
                    page_uid="p1",
                    annotation_type="rect",
                    position=[0.0, 0.0, 1.0, 1.0],
                    color="#000000",
                    width=1.0,
                ),
            ),
        )

    def test_a_cross_bid_annotation_only_paste_copies_no_conditions(self):
        payload = self._annotation_only_paste()
        harness = _Harness({"insert_annotations": ["new-1"]})
        harness.service.queue_plan_items_paste(self.DATABASE, payload, lambda _r: None)
        request, execute, _callback = harness.provider.requests[-1]
        self.assertEqual(
            request.resources, (ResourceRef("annotations_collection", "7", 7),)
        )
        self.assertEqual(execute().outcome_status, MutationOutcomeStatus.COMMITTED)
        self.assertEqual(
            [(name, method) for name, method, _a, _k in harness.calls],
            [("insert_annotations", "execute")],
        )
        harness = _Harness({"insert_annotations": ["new-1"]}, sql=False)
        result = harness.service.execute_plan_items_paste_local(
            self.DATABASE, payload, publish_database_refreshed_after_write=False
        )
        self.assertEqual(result.outcome_status, MutationOutcomeStatus.COMMITTED)
        self.assertEqual(
            [(name, method) for name, method, _a, _k in harness.calls],
            [("insert_annotations", "execute")],
        )
        self.assertNotIn(
            "conditions_collection",
            {r.resource_type for r in harness.executor.requests[-1].resources},
        )
        self.assertEqual(
            dict(result.authoritative_result.created_uid_maps)["conditions"], ()
        )

    def test_a_pasted_takeoff_bound_to_an_existing_parent_depends_on_that_parent(self):
        def dependencies(external):
            payload = PlanItemsPastePayload(
                source_bid_uid="7",
                destination_bid_uid="7",
                takeoff_source_uids=("10", "11"),
                takeoff_specs=(
                    self._spec("0", condition_uid="c1", page_uid="p1"),
                    self._spec("10", condition_uid="c1", page_uid="p1"),
                ),
                takeoff_external_parent_sources=external,
            )
            harness = _Harness()
            harness.service.queue_plan_items_paste(
                self.DATABASE, payload, lambda _r: None
            )
            return set(harness.provider.requests[-1][0].dependency_resources)

        base = {ResourceRef("page", "p1", 7), ResourceRef("condition", "c1", 7)}
        self.assertEqual(dependencies(()), base)
        self.assertEqual(
            dependencies(("11",)), base | {ResourceRef("takeoff", "10", 7)}
        )


class ProjectWriteQueuedSaveSweepTests(unittest.TestCase):
    """Queued saves: change-set emptiness, orphan targets and the captured-version
    contract of a Condition duplicate with Takeoff reassignment. Fakes: the harness
    executor, use-case probes, queue provider and a token service whose version can be
    advanced between queueing and execution (SQL rowversion behaviour is NOT proven)."""

    DATABASE = _Harness.DATABASE

    def test_master_data_and_condition_type_saves_accept_each_kind_of_change_alone(
        self,
    ):
        for label, command in (
            (
                "job statuses",
                lambda s, changes: s.queue_job_statuses_save(
                    self.DATABASE, changes, lambda _r: None
                ),
            ),
            (
                "employees",
                lambda s, changes: s.queue_employees_save(
                    self.DATABASE, changes, lambda _r: None
                ),
            ),
            (
                "pay classes",
                lambda s, changes: s.queue_pay_classes_save(
                    self.DATABASE, changes, lambda _r: None
                ),
            ),
            (
                "condition types",
                lambda s, changes: s.queue_condition_types_save(
                    self.DATABASE, changes, lambda _r: None
                ),
            ),
        ):
            for kind, changes in (
                ("new only", {"new": [{"uid": "n1", "name": "N"}]}),
                ("updated only", {"updated": [{"uid": "5", "name": "U"}]}),
                ("deleted only", {"deleted_uids": ["6"]}),
            ):
                with self.subTest(command=label, changes=kind):
                    harness = _Harness()
                    command(harness.service, changes)
                    self.assertEqual(len(harness.provider.requests), 1)
            for empty in (None, {}, {"new": [], "updated": [], "deleted_uids": []}):
                with self.subTest(command=label, empty=empty):
                    harness = _Harness()
                    with self.assertRaises(ValueError):
                        command(harness.service, empty)
                    self.assertEqual(harness.provider.requests, [])

    def test_duplicating_bids_into_no_project_targets_the_orphan_collection(self):
        for target in (None, ""):
            with self.subTest(target=target):
                harness = _Harness()
                harness.service.queue_bids_duplicate(
                    self.DATABASE, ["7"], target, lambda _r: None
                )
                request = harness.provider.requests[-1][0]
                self.assertEqual(
                    request.dependency_resources,
                    (ResourceRef("project_bids", "orphan"),),
                )
                self.assertEqual(request.resources, (ResourceRef("bid", "7", 7),))

    def _tokens(self, harness):
        class VersionedTokens(_HarnessTokens):
            token = b"\x01" * 8

            def expected_versions(self, database_id, resources):
                self.expected_requests.append((database_id, resources))
                return tuple(
                    ExpectedResourceVersion(resource, ConcurrencyToken(self.token))
                    for resource in resources
                    if resource not in self.missing
                )

        tokens = VersionedTokens()
        harness.service._concurrency_tokens = tokens
        return tokens

    def _reassigning_duplicate(self, harness):
        harness.service.queue_conditions_duplicate(
            self.DATABASE,
            "7",
            ["10"],
            lambda _r: None,
            reassign_takeoffs=ConditionTakeoffReassignment("10", "20", ("30",)),
        )
        return harness.provider.requests[-1]

    def test_a_duplicate_with_reassignment_depends_on_the_reassigned_takeoffs_condition_and_page(
        self,
    ):
        harness = _Harness({"duplicate_conditions": ["c9"]})
        self._tokens(harness)
        request, _execute, _callback = self._reassigning_duplicate(harness)
        self.assertEqual(
            set(request.resources),
            {
                ResourceRef("conditions_collection", "7", 7),
                ResourceRef("takeoff", "30", 7),
            },
        )
        self.assertEqual(
            request.dependency_resources,
            tuple(
                sorted(
                    {
                        ResourceRef("condition", "10", 7),
                        ResourceRef("page", "20", 7),
                        ResourceRef("takeoff", "30", 7),
                        ResourceRef("takeoff", "31", 7),
                    }
                )
            ),
        )
        self.assertEqual(request.page_uid, "20")

    def test_a_duplicate_with_reassignment_keeps_the_versions_captured_at_queue_time(
        self,
    ):
        harness = _Harness({"duplicate_conditions": ["c9"]})
        tokens = self._tokens(harness)
        _request, execute, _callback = self._reassigning_duplicate(harness)
        guarded = {
            ResourceRef("takeoff", "30", 7),
            ResourceRef("takeoff", "31", 7),
            ResourceRef("condition", "10", 7),
            ResourceRef("page", "20", 7),
        }
        database, requested = tokens.expected_requests[0]
        self.assertEqual((database, set(requested)), (self.DATABASE, guarded))
        tokens.token = b"\x02" * 8
        self.assertEqual(execute().outcome_status, MutationOutcomeStatus.COMMITTED)
        baseline = {
            item.resource: item.expected.value
            for item in harness.executor.requests[-1].expected_versions
        }
        self.assertEqual(
            baseline,
            {
                **{resource: b"\x01" * 8 for resource in guarded},
                ResourceRef("conditions_collection", "7", 7): b"\x02" * 8,
            },
        )

    def test_a_duplicate_without_reassignment_takes_its_versions_at_execution(self):
        harness = _Harness({"duplicate_conditions": ["c9"]})
        tokens = self._tokens(harness)
        harness.service.queue_conditions_duplicate(
            self.DATABASE, "7", ["10"], lambda _r: None
        )
        _request, execute, _callback = harness.provider.requests[-1]
        self.assertEqual(tokens.expected_requests, [])
        tokens.token = b"\x03" * 8
        execute()
        self.assertEqual(
            {
                item.resource: item.expected.value
                for item in harness.executor.requests[-1].expected_versions
            },
            {
                ResourceRef("condition", "10", 7): b"\x03" * 8,
                ResourceRef("conditions_collection", "7", 7): b"\x03" * 8,
            },
        )

    def test_a_duplicate_with_reassignment_needs_a_version_for_every_guarded_resource(
        self,
    ):
        harness = _Harness({"duplicate_conditions": ["c9"]})
        tokens = self._tokens(harness)
        tokens.missing = {ResourceRef("page", "20", 7)}
        with self.assertRaisesRegex(
            ValueError, "Refresh the Bid before duplicating and reassigning Takeoffs."
        ):
            self._reassigning_duplicate(harness)
        self.assertEqual(harness.provider.requests, [])


class ProjectWriteQueuedUpdateGuardSweepTests(unittest.TestCase):
    """Remaining input guards of queued updates and the plan property payload. Fakes:
    the harness executor, use-case probes and queue provider."""

    DATABASE = _Harness.DATABASE

    def test_a_queued_condition_update_needs_both_conditions_and_changes(self):
        for label, uids, changes in (
            ("no conditions", [], {"name": "New"}),
            ("only blank conditions", ["", None], {"name": "New"}),
            ("no changes", ["10"], {}),
            ("none changes", ["10"], None),
            ("neither", [], {}),
        ):
            with self.subTest(case=label):
                harness = _Harness()
                with self.assertRaisesRegex(ValueError, "requires items and changes"):
                    harness.service.queue_conditions_update(
                        self.DATABASE, "7", uids, changes, lambda _r: None
                    )
                self.assertEqual(harness.provider.requests, [])
        harness = _Harness()
        harness.service.queue_conditions_update(
            self.DATABASE, "7", ["10", "", "10", "11"], {"name": "New"}, lambda _r: None
        )
        self.assertEqual(
            harness.provider.requests[-1][0].resources,
            (ResourceRef("condition", "10", 7), ResourceRef("condition", "11", 7)),
        )

    def test_a_property_payload_without_captured_ownership_verifies_the_updated_takeoffs(
        self,
    ):
        harness = _Harness(sql=False)
        payload = PlanPropertyPayload.from_updates(
            "takeoff_text", [["30", {"Text": "T"}], ["31", {"Text": "U"}]]
        )
        fields = harness.service._apply_plan_property_payload(
            self.DATABASE, "7", payload, (ResourceRef("takeoff", "30", 7),)
        )
        self.assertEqual(fields, ("text_properties",))
        self.assertEqual(
            harness.executor.verifications, [(self.DATABASE, "7", ("30", "31"), (), ())]
        )


class ProjectWriteModuleBoundarySweepTests(unittest.TestCase):
    def test_the_sql_coordinator_is_a_type_checking_only_dependency(self):
        """The coordinator is named only in a string annotation; importing it at run time
        would make the write service depend on (and risk a cycle with) the coordinator.
        """
        from ost_visualizer.application.services import project_write_service

        self.assertFalse(hasattr(project_write_service, "SqlCollaborationCoordinator"))
        self.assertIs(project_write_service.TYPE_CHECKING, False)


class ProjectWriteLiteralContractSweepTests(unittest.TestCase):
    """Literals the command tables never pin: rejection messages of locked local plan
    commands, default owning surfaces, change-set keys, resource types of paste
    dependencies and reordering fields. Fakes: the harness executor, use-case probes,
    queue provider and project-data stub."""

    DATABASE = _Harness.DATABASE

    def test_locked_local_plan_commands_are_rejected_with_their_own_message(self):
        for label, expected, command in (
            (
                "delete",
                "The database rejected deletion.",
                lambda s: s.execute_plan_items_delete_local(
                    self.DATABASE, "7", ["30"], []
                ),
            ),
            (
                "geometry",
                "The database rejected the geometry update.",
                lambda s: s.execute_plan_geometry_local(
                    self.DATABASE, "7", takeoff_positions=[("30", [1, 2])]
                ),
            ),
            (
                "properties",
                "The database rejected the property update.",
                lambda s: s.execute_plan_properties_local(
                    self.DATABASE, "7", "takeoff_text", [("30", {"Text": "T"})]
                ),
            ),
            (
                "paste",
                "The database rejected paste.",
                lambda s: s.execute_plan_items_paste_local(
                    self.DATABASE,
                    ProjectWritePlanInputSweepTests._annotation_only_paste("7", "7"),
                ),
            ),
        ):
            with self.subTest(command=label):
                harness = _Harness(sql=False)
                harness.data.locked = True
                result = command(harness.service)
                self.assertEqual(result.outcome_status, MutationOutcomeStatus.REJECTED)
                self.assertEqual(result.message, expected)
                self.assertEqual((harness.calls, harness.executor.calls), ([], 0))

    def test_default_owning_surfaces_of_queued_commands(self):
        harness = _Harness()
        harness.service.queue_cancelled_placement_cleanup_delete(
            self.DATABASE, "7", ["30"], lambda _r: None
        )
        self.assertEqual(harness.provider.requests[-1][0].owning_surface, "main-plan")
        harness = _Harness()
        harness.service.queue_plan_items_delete(
            self.DATABASE, "7", ["30"], [], lambda _r: None
        )
        self.assertEqual(harness.provider.requests[-1][0].owning_surface, "main-plan")
        harness = _Harness()
        harness.service.queue_plan_items_delete(
            self.DATABASE,
            "7",
            ["30"],
            [],
            lambda _r: None,
            owning_surface="page-dialog",
        )
        self.assertEqual(harness.provider.requests[-1][0].owning_surface, "page-dialog")
        harness = _Harness()
        self.assertIs(
            harness.service.queue_page_setting_if_sql(
                self.DATABASE, "20", "show_mode", [2]
            ),
            True,
        )
        self.assertEqual(harness.provider.requests[-1][0].owning_surface, "main-plan")
        harness = _Harness()
        harness.service.queue_page_setting_if_sql(
            self.DATABASE, "20", "show_mode", [2], owning_surface="rename-dialog"
        )
        self.assertEqual(
            harness.provider.requests[-1][0].owning_surface, "rename-dialog"
        )

    def test_master_data_saves_write_when_only_one_kind_of_change_is_present(self):
        for key, value in (
            ("new", [{"uid": "n1"}]),
            ("updated", [{"uid": "5"}]),
            ("deleted_uids", ["6"]),
        ):
            for use_case, command in (
                (
                    "save_job_statuses",
                    lambda s, changes: s.save_job_statuses(self.DATABASE, changes),
                ),
                (
                    "save_employees",
                    lambda s, changes: s.save_employees_result(self.DATABASE, changes),
                ),
                (
                    "save_pay_classes",
                    lambda s, changes: s.save_pay_classes(self.DATABASE, changes),
                ),
                (
                    "save_condition_types",
                    lambda s, changes: s.save_condition_types_result(
                        self.DATABASE, changes
                    ),
                ),
            ):
                with self.subTest(command=use_case, change=key):
                    harness = _Harness({use_case: {"n1": "x9"}})
                    command(harness.service, {key: value})
                    self.assertEqual(
                        [(name, method) for name, method, _a, _k in harness.calls],
                        [(use_case, "execute")],
                    )
                    self.assertEqual(len(harness.executor.recorder.changes), 1)

    def test_deleting_condition_folders_without_a_current_bid_uses_the_unknown_collection(
        self,
    ):
        harness = _Harness()
        harness.data.bid_ref = None
        self.assertIs(
            harness.service.delete_condition_folders(self.DATABASE, ["f1"]), True
        )
        self.assertEqual(
            [
                harness.resource_text(resource)
                for resource in harness.executor.requests[-1].resources
            ],
            ["conditions_collection:unknown@None"],
        )
        self.assertEqual(
            [(name, method) for name, method, _a, _k in harness.calls],
            [("delete_condition_folders", "execute")],
        )

    def test_renumbering_conditions_publishes_a_ref_no_reorder(self):
        harness = _Harness()
        harness.service._condition_family_reader = lambda _db, _bid: (
            {"10": Condition(uid="10"), "11": Condition(uid="11")},
            {},
        )
        harness.data.replace_condition_family = lambda *_a: True
        self.assertIs(
            harness.service.renumber_conditions(self.DATABASE, "7", ["11", "10"]), True
        )
        self.assertEqual(
            [(event.__name__, payload) for event, payload in harness.events.published],
            [
                (
                    "ConditionsChangedEvent",
                    {
                        "database_id": self.DATABASE,
                        "bid_uid": "7",
                        "condition_uids": ["11", "10"],
                        "changed_fields": ["ref_no"],
                        "change_operations": ["reorder"],
                        "invalidates_undo": False,
                        "local_completion": True,
                    },
                )
            ],
        )

    @staticmethod
    def _two_page_paste(*, annotation_layer="40", takeoff_parents=("0",)):
        specs = tuple(
            ProjectWritePlanInputSweepTests._spec(
                parent, condition_uid="c1", page_uid="p1", area_uid="5"
            )
            for parent in takeoff_parents
        )
        return PlanItemsPastePayload(
            source_bid_uid="7",
            destination_bid_uid="7",
            takeoff_source_uids=tuple(f"t{i}" for i in range(len(specs))),
            takeoff_specs=specs,
            annotation_source_uids=(annotation_resource_id("rect", "a1"),),
            annotation_specs=(
                InsertAnnotationSpec(
                    page_uid="p2",
                    annotation_type="rect",
                    position=[0.0, 0.0, 1.0, 1.0],
                    color="#000000",
                    width=1.0,
                    layer_uid=annotation_layer,
                ),
            ),
        )

    def test_a_paste_depends_on_its_pages_areas_and_layers(self):
        payload = self._two_page_paste()
        expected = {
            ResourceRef("page", "p1", 7),
            ResourceRef("page", "p2", 7),
            ResourceRef("condition", "c1", 7),
            ResourceRef("area", "5", 7),
            ResourceRef("layer", "40", 7),
        }
        harness = _Harness()
        harness.service.queue_plan_items_paste(self.DATABASE, payload, lambda _r: None)
        request = harness.provider.requests[-1][0]
        self.assertEqual(set(request.dependency_resources), expected)
        self.assertEqual(request.page_uid, "")
        harness = _Harness(
            {"insert_takeoffs": ["n1"], "insert_annotations": ["a-new"]}, sql=False
        )
        result = harness.service.execute_plan_items_paste_local(
            self.DATABASE, payload, publish_database_refreshed_after_write=False
        )
        self.assertEqual(result.outcome_status, MutationOutcomeStatus.COMMITTED)
        self.assertTrue(expected.issubset(set(harness.executor.requests[-1].resources)))
        # a paste on one page names that page; without a layer there is no Layer dependency
        single = PlanItemsPastePayload(
            source_bid_uid="7",
            destination_bid_uid="7",
            annotation_source_uids=(annotation_resource_id("rect", "a1"),),
            annotation_specs=(
                InsertAnnotationSpec(
                    page_uid="p2",
                    annotation_type="rect",
                    position=[0.0, 0.0, 1.0, 1.0],
                    color="#000000",
                    width=1.0,
                ),
            ),
        )
        harness = _Harness()
        harness.service.queue_plan_items_paste(self.DATABASE, single, lambda _r: None)
        request = harness.provider.requests[-1][0]
        self.assertEqual(request.page_uid, "p2")
        self.assertEqual(
            set(request.dependency_resources), {ResourceRef("page", "p2", 7)}
        )

    def test_a_pasted_takeoff_with_a_root_parent_marker_has_no_parent_dependency(self):
        for parent in ("0", "None", None):
            with self.subTest(parent=parent):
                harness = _Harness()
                harness.service.queue_plan_items_paste(
                    self.DATABASE,
                    self._two_page_paste(takeoff_parents=(parent,)),
                    lambda _r: None,
                )
                dependencies = harness.provider.requests[-1][0].dependency_resources
                self.assertEqual(
                    [r for r in dependencies if r.resource_type == "takeoff"], []
                )
        harness = _Harness()
        harness.service.queue_plan_items_paste(
            self.DATABASE,
            self._two_page_paste(takeoff_parents=("99",)),
            lambda _r: None,
        )
        self.assertIn(
            ResourceRef("takeoff", "99", 7),
            harness.provider.requests[-1][0].dependency_resources,
        )

    def test_a_queued_duplicate_with_reassignment_reports_conditions_and_takeoffs(self):
        harness = _Harness({"duplicate_conditions": ["c9"]})
        harness.tokens.guard = True
        harness.service.queue_conditions_duplicate(
            self.DATABASE,
            "7",
            ["10"],
            lambda _r: None,
            reassign_takeoffs=ConditionTakeoffReassignment("10", "20", ("30",)),
        )
        _request, execute, _callback = harness.provider.requests[-1]
        result = execute()
        self.assertEqual(result.outcome_status, MutationOutcomeStatus.COMMITTED)
        authoritative = result.authoritative_result
        self.assertEqual(authoritative.affected_families, ("conditions", "takeoffs"))
        self.assertEqual(authoritative.affected_condition_uids, ("10", "c9"))
        self.assertEqual(authoritative.affected_page_uids, ("20",))
        self.assertEqual(
            authoritative.updated_resources, (ResourceRef("takeoff", "30", 7),)
        )
        harness = _Harness({"duplicate_conditions": ["c9"]})
        harness.service.queue_conditions_duplicate(
            self.DATABASE, "7", ["10"], lambda _r: None
        )
        authoritative = harness.provider.requests[-1][1]().authoritative_result
        self.assertEqual(authoritative.affected_families, ("conditions",))
        self.assertEqual(authoritative.affected_condition_uids, ("c9",))
        self.assertEqual(authoritative.affected_page_uids, ())
