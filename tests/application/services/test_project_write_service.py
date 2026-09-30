from ost_visualizer.domain.entities.takeoff import Takeoff
from ost_visualizer.domain.entities.identity_refs import BidRef
from ost_visualizer.application.services.project_write_service import (
    ProjectWriteService,
)
from ost_visualizer.application.dtos.insert_takeoff_spec_dto import InsertTakeoffSpec
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
from types import SimpleNamespace
import uuid
import unittest
import os
from contextlib import nullcontext
from ost_visualizer.application.dtos.collaboration_dtos import (
    CollaborationShutdownState,
    DatabaseMutationResult,
    MutationOutcomeStatus,
    QueuedMutationResult,
)
from ost_visualizer.application.services.project_write_service import (
    ProjectWriteService,
    WriteReloadResult,
)
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
import logging
from dataclasses import replace
from unittest.mock import Mock, patch
from ost_visualizer.application.dtos.collaboration_dtos import (
    EditLeaseHandle,
    EditLeaseResult,
    MutationOutcomeStatus,
    QueuedMutationResult,
)
from ost_visualizer.application.events.app_events import AppEvents
from ost_visualizer.application.use_cases.project.save_page_scale_use_case import (
    SavePageScaleUseCase,
)
from ost_visualizer.domain.aggregates.ost_aggregate import OstAggregate
from ost_visualizer.domain.entities.bid import Bid
from ost_visualizer.domain.entities.page import Page
from ost_visualizer.domain.services.project_data_service import ProjectDataService
from ost_visualizer.infrastructure.events.event_bus import EventBus
from ost_visualizer.presentation.coordinators.ui_event_coordinator import (
    UIEventCoordinator,
)
from PySide6 import QtWidgets
from ost_visualizer.application.dtos.collaboration_dtos import (
    ChangeOperation,
    DatabaseMutationResult,
    MutationOutcomeStatus,
    QueuedMutationResult,
    ResourceRef,
    SynchronizationConflict,
    SynchronizationConflictKind,
)
from ost_visualizer.application.dtos.update_condition_dto import (
    UpdateConditionDto,
    UpdateConditionResultDto,
)
from ost_visualizer.application.interfaces.i_mdb_connection_manager import (
    DatabaseConnectionUnavailableError,
)
from ost_visualizer.application.services.active_bid_write_guard import (
    ActiveBidWriteGuard,
)
from ost_visualizer.application.services.project_write_service import (
    DeleteValidationResult,
    ProjectWriteService,
    WriteReloadResult,
)
from ost_visualizer.domain.entities.area import BidArea, BidAreaChangeset
from ost_visualizer.domain.entities.condition import Condition
from ost_visualizer.domain.entities.hierarchy_data import (
    HierarchyBidInfo,
    HierarchyData,
    HierarchyFileEntry,
    HierarchyProjectInfo,
)
from tests.application.services.write_permission_support import (
    _ConcurrencyTokens as _permissions__ConcurrencyTokens,
    _DatabaseCapability as _permissions__DatabaseCapability,
    _EventBus as _permissions__EventBus,
    _ForbiddenUseCase as _permissions__ForbiddenUseCase,
    _MutationExecutor as _permissions__MutationExecutor,
    _MutationRecorder as _permissions__MutationRecorder,
    _ProjectData as _permissions__ProjectData,
    _SequenceUseCase as _permissions__SequenceUseCase,
    _SessionRegistry as _permissions__SessionRegistry,
    _UseCase as _permissions__UseCase,
    _hierarchy_with_bids as _permissions__hierarchy_with_bids,
    _write_service as _permissions__write_service,
)
from copy import deepcopy
from ost_visualizer.application.dtos.collaboration_dtos import (
    DatabaseMutationResult,
    MutationOutcomeStatus,
)
import tests.application.services.test_project_write_service as parity
import tests.presentation.components.plan_view.components.test_placement_mode as placement_fixtures
from ost_visualizer.application.dtos.collaboration_dtos import (
    DatabaseMutationResult,
    EditLeaseHandle,
    MutationOutcomeStatus,
    PlanItemsPastePayload,
    ProjectWritePayload,
    QueuedMutationResult,
    ResourceRef,
)
from ost_visualizer.application.dtos.collaboration_resource_catalog import (
    annotation_resource_id,
)
from ost_visualizer.application.dtos.create_condition_spec_dto import (
    CreateConditionSpec,
)
from ost_visualizer.application.dtos.insert_annotation_spec_dto import (
    InsertAnnotationSpec,
)
from ost_visualizer.application.dtos.update_condition_dto import (
    UpdateConditionResultDto,
)
from ost_visualizer.application.services.project_write_service import (
    DeleteValidationResult,
    ProjectWriteService,
)
from ost_visualizer.domain.entities.employee import Employee
from ost_visualizer.application.dtos.collaboration_dtos import (
    MutationOutcomeStatus,
    QueuedMutationResult,
)
from tests.presentation.handlers.test_plan_view_action_handler import (
    FakeAccess,
    FakeDeferredPersistence,
    FakeEventBus,
    FakePageSettingsBar,
    FakePlanView,
    FakeProjectData,
    FakeUiState,
    FakeWriteService,
)
import math
from tests.integration.annotations.family_support import (
    AnnotationFamilyGeometry as _family_support_AnnotationFamilyGeometry,
)


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
    def record(self, *_args, **_kwargs):
        pass


class _CapturedQueueProvider:
    def __init__(self) -> None:
        self.requests = []

    def uses_sql_collaboration(self, _database_id: str) -> bool:
        return True

    def queue_request(self, request, execute, callback, **_options):
        self.requests.append((request, execute, callback))
        return 41


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


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
                value=["501"],
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
        self.assertEqual(work_result.created_resource_ids, ("501",))
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
        self.assertTrue(kwargs["result_validator"](work_result))
        self.assertNotIn("allow_resource_overlap", kwargs)
        self.assertEqual(generation, 7)
        self.assertEqual(
            insert_calls[0]["consistency_resources"],
            request.dependency_resources,
        )
        self.assertFalse(insert_calls[0]["publish_conflict_event"])

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

    def test_page_area_write_can_skip_database_refresh(self):
        calls = []
        service = ProjectWriteService.__new__(ProjectWriteService)
        service._database_capability_service = SimpleNamespace(
            is_editable=lambda _locator, resource=None: True
        )
        service._project_data = SimpleNamespace(
            get_current_bid_ref=lambda: BidRef("a.mdb", "1")
        )
        service._bid_write_guard = SimpleNamespace(
            blocks_active_locked_bid_write=lambda _file_path, bid_uid=None: False
        )
        service._save_page_area = SimpleNamespace(
            execute=lambda db_path, page_uid, area_uid: calls.append(
                ("write", db_path, page_uid, area_uid)
            )
            or True
        )
        service._reload_after_success = lambda db_path, success, publish=True: (
            calls.append(("reload_after_success", db_path, success, publish)) or success
        )
        service._mutation_executor = SimpleNamespace(
            execute=lambda request, operation: DatabaseMutationResult(
                operation_id=request.operation_id,
                outcome_status=MutationOutcomeStatus.COMMITTED,
                value=operation(
                    SimpleNamespace(
                        record=lambda _resource, _operation, changed_fields=(), payload="": None
                    )
                ),
            )
        )
        service._session_registry = SimpleNamespace(
            get=lambda _database_id: "",
            lock_tokens=lambda _database_id, _resources: (),
        )
        service._concurrency_tokens = SimpleNamespace(
            mutation_scope=lambda _database_id: nullcontext(),
            ensure_resources_loaded=lambda _database_id, _resources: None,
            expected_versions=lambda _database_id, _resources: (),
            apply_result=lambda _database_id, _versions: None,
        )
        service._event_bus = SimpleNamespace(publish=lambda *_args, **_kwargs: None)
        self.assertTrue(
            service.save_page_area(
                "a.mdb",
                "p1",
                "2",
                publish_database_refreshed_after_write=False,
            )
        )
        self.assertEqual(
            calls,
            [
                ("write", "a.mdb", "p1", "2"),
                ("reload_after_success", "a.mdb", True, False),
            ],
        )


class ProjectWriteQueueContractTests(unittest.TestCase):
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
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def setUp(self):
        self.bid_ref = BidRef("test.mdb", "7")
        self.original = Page(uid="42", name="Page 42", scale_factor2=48.0)
        self.model = OstAggregate(Mock())
        self.model.current_bid_ref = self.bid_ref
        self.model.current_bid = Bid("7", "Test bid")
        self.model.set_pages({"42": self.original})
        self.data = ProjectDataService(self.model)
        self.persisted = {"42": self.original}
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
            lambda _db, _resources, operation, **_kw: SimpleNamespace(
                outcome_status=MutationOutcomeStatus.COMMITTED, value=operation(Mock())
            )
        )
        self.writer = Mock()
        self.writer.save_page_scale.side_effect = self._write
        self.service._save_page_scale = SavePageScaleUseCase(self.writer)
        self.coordinator = object.__new__(UIEventCoordinator)
        self.coordinator.main_window = None
        self.coordinator.event_bus = self.events
        self.coordinator._icon_provider = None
        self.coordinator.project_data = self.data
        self.coordinator.ui_state_manager = SimpleNamespace(
            active_page_uid="42",
            get_selected_bid_ref=lambda: self.model.current_bid_ref,
        )
        self.coordinator.ui_access_manager = Mock()
        self.coordinator.ui_access_manager.is_allowed.return_value = True
        self.coordinator.takeoff_sidebar = SimpleNamespace(
            get_page_order=lambda: list(self.persisted)
        )
        self.coordinator._deferred_persistence = Mock()
        self.coordinator._deferred_persistence.flush_for_file.return_value = True
        self.coordinator._project_write_service = self.service

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
        self.assertEqual(len(changes), 1)
        self.assertEqual(changes[0]["page_uids"], ("42",))

    def test_scale_save_does_not_project_into_bid_selected_during_write(self):
        replacement = Page(uid="42", name="Other bid page", scale_factor2=24.0)
        resources = []

        def execute(_database, requested, operation, **_options):
            resources.extend(requested)
            value = operation(Mock())
            self.model.current_bid_ref = BidRef("test.mdb", "8")
            self.model.current_bid = Bid("8", "Other bid")
            self.model.set_pages({"42": replacement})
            return SimpleNamespace(
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

    def test_revoked_database_capability_blocks_deferred_write_execution(self):
        service, *_unused = _permissions__write_service(
            _permissions__ProjectData(),
            database_capability=_permissions__DatabaseCapability(editable=False),
        )
        self.assertTrue(service.is_expected_deferred_write_blocked("sql-db"))

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
        service._update_condition = _permissions__UseCase(
            UpdateConditionResultDto(success=True)
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
                [],
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
        self.assertEqual(1, len(update_bid_job_status.calls))

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
        self.assertEqual(1, len(delete_bids.calls))
        self.assertEqual(1, len(duplicate_bid.calls))

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
            SimpleNamespace(),
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
            [{"new_0": "employee-new"}]
        )
        changes = {
            "new": [SimpleNamespace(uid="new_0")],
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

    def test_employee_save_result_can_skip_database_refresh(self):
        project_data = _permissions__ProjectData()
        service, *_ = _permissions__write_service(project_data)
        reload_calls = []
        service._reload_database = (
            lambda file_path: reload_calls.append(file_path) or True
        )
        service._save_employees = _permissions__UseCase({"new_0": "employee-new"})
        changes = {
            "new": [SimpleNamespace(uid="new_0")],
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

    def test_mdb_condition_type_save_refreshes_sidebar_without_database_event(self):
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
                "folder-1": SimpleNamespace(parent_uid=None)
            },
            get_bid_conditions=lambda: {
                "cond-1": SimpleNamespace(folder_uid="folder-1")
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
                "folder-1": SimpleNamespace(parent_uid=None)
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
    @classmethod
    def setUpClass(cls):
        placement_fixtures.TakeoffLifecyclePlacementTests.setUpClass()

    def test_nested_parent_paste_remaps_each_generation_on_both_backends(self):
        payload = parity.MdbSqlBehaviorParityTests._mixed_paste_payload()
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
                        parity.MdbSqlBehaviorParityTests._queued_project_service()
                    )
                else:
                    service = (
                        parity.MdbSqlBehaviorParityTests._local_composite_service()
                    )
                service._insert_takeoffs = parity._SequenceUseCase(
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
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    @staticmethod
    def _local_composite_service():
        service = ProjectWriteService.__new__(ProjectWriteService)
        service.uses_sql_collaboration_mutations = lambda _database_id: False
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

    def test_sql_plan_paste_locks_existing_hot_link_named_view_dependency(self):
        service, provider = self._queued_project_service()
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

        def execute_mutation(database_id, resources, operation, **options):
            value = operation(_Recorder())
            return DatabaseMutationResult(
                operation_id=options["operation_id"],
                outcome_status=MutationOutcomeStatus.COMMITTED,
                value=value,
                commit_attempted=True,
            )

        service._execute_database_mutation = execute_mutation
        return service, provider

    def test_sql_page_and_layer_commands_are_deferred_to_collaboration_queue(self):
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
        for write_kind, submit, use_case_name in command_cases:
            with self.subTest(write_kind=write_kind):
                service, provider = self._queued_project_service()
                sequence = submit(service)
                self.assertEqual(sequence, 41)
                use_case = getattr(service, use_case_name)
                self.assertEqual(use_case.calls, [])
                request, execute, _callback = provider.requests[0]
                self.assertIsInstance(request.payload, ProjectWritePayload)
                self.assertEqual(request.payload.write_kind, write_kind)
                if write_kind == "update_all_layers_show":
                    self.assertEqual(
                        request.payload.values_json,
                        '{"layer_uids":["70","71"],"show":false}',
                    )
                result = execute()
                self.assertEqual(result.outcome_status, MutationOutcomeStatus.COMMITTED)
                self.assertEqual(len(use_case.calls), 1)
                if write_kind == "update_all_layers_show":
                    self.assertEqual(
                        use_case.calls,
                        [("database", "7", False, ["70", "71"])],
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
                service = parity.MdbSqlBehaviorParityTests._local_composite_service()
                service._event_bus = FakeEventBus()
                queued = []
                service._queue_project_write = (
                    lambda *args, **_kwargs: queued.append(args) or 1
                )
                completed = []
                changes = BidAreaChangeset([], [], ["2"])
                service.queue_bid_areas_save("bid.mdb", "7", changes, completed.append)
                self.assertEqual(service._event_bus.events, [])
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
                        service._event_bus.events,
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
                    self.assertEqual(service._event_bus.events, [])

    def test_queued_area_save_persists_the_same_snapshot_as_its_delete_event(self):
        service, provider = parity.MdbSqlBehaviorParityTests._queued_project_service()
        service._event_bus = FakeEventBus()
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


class QueuedAnnotationSnapshotTests(unittest.TestCase):
    def test_each_family_queue_keeps_geometry_style_and_page_from_submission(self):
        import tests.application.services.test_project_write_service as fixtures
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
        ) in _family_support_AnnotationFamilyGeometry.POSITIONS.items():
            with self.subTest(kind=kind):
                service, provider = (
                    fixtures.MdbSqlBehaviorParityTests._queued_project_service()
                )
                service._insert_annotations = fixtures._SequenceUseCase(["new"])
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
                execute()
                captured = service._insert_annotations.calls[0][2][0]
                self.assertEqual(captured.page_uid, "p1")
                self.assertEqual(captured.position, position)
                self.assertEqual(captured.properties["Text"], "Before")
                self.assertEqual(captured.color, "#123456")
                self.assertEqual(
                    request.payload.annotation_specs[0].page_uid, request.page_uid
                )
