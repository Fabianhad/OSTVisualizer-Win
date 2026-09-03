import logging
import unittest
import uuid
from types import SimpleNamespace
from PySide6 import QtWidgets
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
from ost_visualizer.application.dtos.insert_annotation_spec_dto import (
    InsertAnnotationSpec,
)
from ost_visualizer.application.dtos.insert_takeoff_spec_dto import InsertTakeoffSpec
from ost_visualizer.application.dtos.create_condition_spec_dto import (
    CreateConditionSpec,
)
from ost_visualizer.application.dtos.update_condition_dto import (
    UpdateConditionResultDto,
)
from ost_visualizer.application.services.project_write_service import (
    DeleteValidationResult,
    ProjectWriteService,
)
from ost_visualizer.domain.entities.identity_refs import BidRef
from ost_visualizer.domain.entities.condition import Condition
from ost_visualizer.domain.entities.employee import Employee
from ost_visualizer.domain.entities.cover_sheet import JobStatus
from ost_visualizer.presentation.coordinators.ui_event_coordinator import (
    UIEventCoordinator,
)
from ost_visualizer.presentation.managers.deferred_persistence_manager import (
    DeferredPersistenceManager,
)
from ost_visualizer.presentation.services.selection_commands import (
    InsertTakeoffsCommand,
)
from ost_visualizer.presentation.services.undo_redo_service import UndoRedoService


class _PageViewWriteService:
    def __init__(self, *, sql: bool) -> None:
        self.sql = sql
        self.local_write_calls = 0

    def queue_page_setting_if_sql(self, *_args, **_kwargs):
        return False if self.sql else None

    def save_page_view_state(self, *_args, **_kwargs):
        self.local_write_calls += 1
        return False

    def save_bid_selected_page(self, *_args, **_kwargs):
        return False

    def is_expected_deferred_write_blocked(self, _database_id: str) -> bool:
        return False


class _SqlWorkspaceService:
    def __init__(self, *, sql: bool) -> None:
        self.sql = sql
        self.write_calls = 0

    def uses_sql_workspace(self, _database_id: str) -> bool:
        return self.sql

    def save_page_view(self, *_args, **_kwargs):
        self.write_calls += 1

    def save_active_page(self, *_args, **_kwargs):
        self.write_calls += 1


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


class MdbSqlBehaviorParityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    @staticmethod
    def _result(status: MutationOutcomeStatus) -> QueuedMutationResult:
        return QueuedMutationResult(
            database_id="database",
            runtime_generation=1,
            operation_id=str(uuid.uuid4()),
            outcome_status=status,
            commit_attempted=status == MutationOutcomeStatus.COMMITTED,
        )

    def test_sql_bid_lock_state_uses_hydrated_navigation_snapshot(self):
        locked_values = []
        coordinator = SimpleNamespace(
            project_data=SimpleNamespace(
                get_bid=lambda _bid_ref: SimpleNamespace(status="Locked"),
                get_job_status_snapshot=lambda _database_id: [
                    JobStatus(uid="status-1", name="Locked", locked=True)
                ],
                set_current_bid_locked=locked_values.append,
            ),
            _project_write_service=SimpleNamespace(
                uses_sql_collaboration_mutations=lambda _database_id: True
            ),
            _project_read_service=SimpleNamespace(
                is_bid_locked=lambda *_args: self.fail(
                    "SQL bid activation must not query the database on the Qt thread"
                )
            ),
        )
        UIEventCoordinator._resolve_bid_lock_state(
            coordinator, BidRef("sql-database", "bid-1")
        )
        self.assertEqual(locked_values, [True])

    def test_mdb_bid_lock_state_keeps_local_reader_strategy(self):
        locked_values = []
        read_calls = []
        coordinator = SimpleNamespace(
            project_data=SimpleNamespace(
                get_bid=lambda _bid_ref: SimpleNamespace(status="Locked"),
                get_job_status_snapshot=lambda _database_id: self.fail(
                    "MDB lock state must retain its local reader strategy"
                ),
                set_current_bid_locked=locked_values.append,
            ),
            _project_write_service=SimpleNamespace(
                uses_sql_collaboration_mutations=lambda _database_id: False
            ),
            _project_read_service=SimpleNamespace(
                is_bid_locked=lambda database_id, status: (
                    read_calls.append((database_id, status)) or True
                )
            ),
        )
        UIEventCoordinator._resolve_bid_lock_state(
            coordinator, BidRef("local.mdb", "bid-1")
        )
        self.assertEqual(read_calls, [("local.mdb", "Locked")])
        self.assertEqual(locked_values, [True])

    def test_main_sql_scale_failure_restores_only_its_current_page(self):
        callbacks = []
        refreshes = []

        def queue_page_setting(*_args, **kwargs):
            callbacks.append(kwargs["callback"])
            return True

        state = SimpleNamespace(
            active_page_uid="page-1",
            get_selected_bid_ref=lambda: BidRef("sql-database", "bid-1"),
        )
        coordinator = SimpleNamespace(
            _flush_deferred_for_file=lambda _database_id: True,
            _project_write_service=SimpleNamespace(
                queue_page_setting_if_sql=queue_page_setting,
                save_page_scale=lambda *_args: self.fail(
                    "SQL scale changes must not use the synchronous write path"
                ),
            ),
            ui_state_manager=state,
            _update_page_settings_bar=refreshes.append,
        )
        UIEventCoordinator._on_page_scale_changed(
            coordinator, "sql-database", "page-1", 0.25, 12.0
        )
        callbacks[0](self._result(MutationOutcomeStatus.COMMITTED_PROJECTION_FAILED))
        self.assertEqual(refreshes, [])
        state.active_page_uid = "page-2"
        callbacks[0](self._result(MutationOutcomeStatus.CONFLICT))
        self.assertEqual(refreshes, [])
        state.active_page_uid = "page-1"
        callbacks[0](self._result(MutationOutcomeStatus.CONFLICT))
        self.assertEqual(refreshes, ["page-1"])

    def test_failed_history_operation_stays_undoable_for_mdb_and_sql(self):
        for backend in ("mdb", "sql"):
            with self.subTest(backend=backend):
                history = UndoRedoService()
                history.set_active_bid(BidRef("database", "7"))
                if backend == "mdb":
                    view = SimpleNamespace(
                        clear_selection=lambda: None,
                        set_selected_uids=lambda _uids: None,
                    )
                    command = InsertTakeoffsCommand(
                        ["1"],
                        BidRef("database", "7"),
                        [object()],
                        None,
                        view,
                        insert_takeoffs_fn=lambda _bid, _specs: ["2"],
                        delete_takeoffs_fn=lambda _path, _uids: False,
                    )
                    history.push_local(command.undo, command.redo)
                else:
                    history.push(
                        lambda complete: complete(
                            self._result(MutationOutcomeStatus.REJECTED)
                        ),
                        lambda complete: complete(
                            self._result(MutationOutcomeStatus.COMMITTED)
                        ),
                    )
                history.undo()
                self.assertTrue(history.can_undo())
                self.assertFalse(history.can_redo())

    def test_committed_history_operation_advances_for_mdb_and_sql(self):
        for backend in ("mdb", "sql"):
            with self.subTest(backend=backend):
                history = UndoRedoService()
                history.set_active_bid(BidRef("database", "7"))
                if backend == "mdb":
                    history.push_local(lambda: True, lambda: True)
                else:
                    history.push(
                        lambda complete: complete(
                            self._result(MutationOutcomeStatus.COMMITTED)
                        ),
                        lambda complete: complete(
                            self._result(MutationOutcomeStatus.COMMITTED)
                        ),
                    )
                history.undo()
                self.assertFalse(history.can_undo())
                self.assertTrue(history.can_redo())

    def test_noncritical_page_view_is_abandoned_on_shutdown_for_either_backend(self):
        for backend in ("mdb", "sql"):
            with self.subTest(backend=backend):
                writes = _PageViewWriteService(sql=backend == "sql")
                workspace = _SqlWorkspaceService(sql=backend == "sql")
                manager = DeferredPersistenceManager(
                    writes,
                    workspace,
                    logger_=logging.getLogger(
                        f"tests.mdb_sql_behavior_parity.{backend}"
                    ),
                )
                manager.schedule_page_view_state(
                    "database",
                    "7",
                    "107",
                    2.0,
                    10.0,
                    20.0,
                )
                self.assertTrue(manager.cleanup())
                self.assertEqual(manager.pending_count, 0)
                self.assertEqual(writes.local_write_calls, 0)
                self.assertEqual(workspace.write_calls, 1 if backend == "sql" else 0)

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
                result = execute()
                self.assertEqual(result.outcome_status, MutationOutcomeStatus.COMMITTED)
                self.assertEqual(len(use_case.calls), 1)

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


if __name__ == "__main__":
    unittest.main()
