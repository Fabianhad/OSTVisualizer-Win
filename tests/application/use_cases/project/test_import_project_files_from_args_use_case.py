from __future__ import annotations
import logging
import tempfile
import unittest
import uuid
from pathlib import Path
from types import SimpleNamespace
from ost_visualizer.application.dtos.collaboration_dtos import (
    MutationOutcomeStatus,
    QueuedMutationResult,
)
from ost_visualizer.application.dtos.file_import_args import (
    PROJECT_IMPORT_EXTENSION_OSP,
    PROJECT_IMPORT_EXTENSION_OST,
    parse_project_file_args,
)
from ost_visualizer.application.use_cases.project import (
    import_project_files_from_args_use_case as import_args_use_case,
)
from ost_visualizer.domain.entities.database_descriptor import (
    DatabaseDescriptor,
    SqlServerDatabaseLocation,
)
from ost_visualizer.domain.entities.file_state import FileEntry
from ost_visualizer.domain.entities.hierarchy_data import (
    HierarchyBidInfo,
    HierarchyData,
    HierarchyFileEntry,
    HierarchyProjectInfo,
)
from ost_visualizer.domain.entities.project_constants import (
    DELETED_BIDS_PROJECT_NAME,
    DELETED_BIDS_PROJECT_UID,
)
from ost_visualizer.domain.entities.workspace_state import (
    WORKSPACE_NODE_KIND_BID,
    WORKSPACE_NODE_KIND_PROJECT,
    ProjectTreeSelectionState,
    WorkspaceState,
)
from ost_visualizer.infrastructure.sql.schema_definition import SQL_SCHEMA_V1
from tests.helpers.startup_import import (
    FakeImportService as _startup_import_FakeImportService,
    FakeProjectData as _startup_import_FakeProjectData,
    _project_file_args as _startup_import__project_file_args,
)


def _quiet_logger():
    logger = logging.getLogger("test.import_project_files_from_args")
    logger.addHandler(logging.NullHandler())
    logger.propagate = False
    return logger


class ImportProjectFilesFromArgsTests(unittest.TestCase):
    def test_sql_multi_file_import_uses_independent_ordered_durable_results(self):
        with tempfile.TemporaryDirectory() as tmp:
            first = Path(tmp) / "first.ost"
            second = Path(tmp) / "second.osp"
            first.write_text("ost")
            second.write_text("osp")
            service = _startup_import_FakeImportService()
            service.sql_collaboration = True
            target = import_args_use_case.ProjectImportTarget("sql-database")
            use_case = import_args_use_case.ImportProjectFilesFromArgsUseCase(
                service,
                _startup_import_FakeProjectData("sql-database"),
                SimpleNamespace(file_entries=[]),
                SimpleNamespace(),
            )
            completed = []
            use_case.queue_imports(
                _startup_import__project_file_args(first, second),
                target,
                completed.append,
            )
            self.assertEqual(len(service.queued_imports), 2)
            self.assertEqual(
                [call[1] for call in service.queued_imports], ["ost", "osp"]
            )
            service.queued_imports[0][4](
                QueuedMutationResult(
                    database_id="sql-database",
                    runtime_generation=1,
                    operation_id=str(uuid.uuid4()),
                    outcome_status=MutationOutcomeStatus.COMMITTED,
                )
            )
            self.assertEqual(completed, [])
            service.queued_imports[1][4](
                QueuedMutationResult(
                    database_id="sql-database",
                    runtime_generation=1,
                    operation_id=str(uuid.uuid4()),
                    outcome_status=MutationOutcomeStatus.CONFLICT,
                    message="conflicting import",
                )
            )
            self.assertEqual(len(completed), 1)
            self.assertEqual(completed[0].succeeded, 1)
            self.assertEqual(completed[0].failed, 1)
            self.assertEqual(
                [result.outcome_status for result in completed[0].results],
                [MutationOutcomeStatus.COMMITTED, MutationOutcomeStatus.CONFLICT],
            )
            self.assertEqual(
                [result.source_path for result in completed[0].results],
                [str(first.resolve()), str(second.resolve())],
            )
            self.assertEqual(
                [result.success for result in completed[0].results], [True, False]
            )
            self.assertEqual(
                [result.message for result in completed[0].results],
                ["Imported successfully.", "conflicting import"],
            )
            self.assertEqual(
                [result.project_name for result in completed[0].results],
                ["first", None],
            )
            self.assertEqual(completed[0].target_db_path, "sql-database")
            self.assertEqual(
                [(call[0], call[2], call[3]) for call in service.queued_imports],
                [
                    (str(first.resolve()), "sql-database", None),
                    (str(second.resolve()), "sql-database", None),
                ],
            )

    def test_sql_multi_file_import_reports_results_in_argument_order(self):
        with tempfile.TemporaryDirectory() as tmp:
            first = Path(tmp) / "first.ost"
            second = Path(tmp) / "second.osp"
            first.write_text("ost")
            second.write_text("osp")
            service = _startup_import_FakeImportService()
            use_case = import_args_use_case.ImportProjectFilesFromArgsUseCase(
                service,
                _startup_import_FakeProjectData("sql-database"),
                SimpleNamespace(file_entries=[]),
                SimpleNamespace(),
            )
            completed = []
            use_case.queue_imports(
                _startup_import__project_file_args(first, second),
                import_args_use_case.ProjectImportTarget("sql-database", "project-1"),
                completed.append,
            )
            self.assertEqual(
                [call[3] for call in service.queued_imports],
                ["project-1", "project-1"],
            )

            def committed():
                return QueuedMutationResult(
                    database_id="sql-database",
                    runtime_generation=1,
                    operation_id=str(uuid.uuid4()),
                    outcome_status=MutationOutcomeStatus.COMMITTED,
                )

            service.queued_imports[1][4](committed())
            self.assertEqual(completed, [])
            service.queued_imports[0][4](committed())
            service.queued_imports[0][4](committed())
            self.assertEqual(len(completed), 1)
            self.assertEqual(
                [result.project_name for result in completed[0].results],
                ["first", "second"],
            )
            self.assertEqual(completed[0].selected_project_uid, "project-1")
            self.assertEqual(completed[0].succeeded, 2)

    def test_sql_queue_reports_vanished_source_and_queue_failure_without_hanging(self):
        with tempfile.TemporaryDirectory() as tmp:
            existing = Path(tmp) / "existing.ost"
            existing.write_text("ost")
            vanished = Path(tmp) / "vanished.osp"

            class RaisingService(_startup_import_FakeImportService):
                def queue_project_import(self, *args):
                    raise RuntimeError("queue closed")

            service = RaisingService()
            use_case = import_args_use_case.ImportProjectFilesFromArgsUseCase(
                service,
                _startup_import_FakeProjectData("sql-database"),
                SimpleNamespace(file_entries=[]),
                SimpleNamespace(),
                logger=_quiet_logger(),
            )
            args = import_args_use_case.ProjectFileArgs(
                files=[
                    import_args_use_case.ParsedProjectFileArg(
                        str(vanished), PROJECT_IMPORT_EXTENSION_OSP
                    ),
                    import_args_use_case.ParsedProjectFileArg(
                        str(existing), PROJECT_IMPORT_EXTENSION_OST
                    ),
                ],
                rejected=[import_args_use_case.RejectedProjectFileArg("x.txt", "bad")],
            )
            completed = []
            use_case.queue_imports(
                args,
                import_args_use_case.ProjectImportTarget("sql-database"),
                completed.append,
            )
            self.assertEqual(len(completed), 1)
            batch = completed[0]
            self.assertEqual(
                [(r.message, r.outcome_status, r.success) for r in batch.results],
                [
                    (
                        "File does not exist.",
                        MutationOutcomeStatus.REJECTED,
                        False,
                    ),
                    (
                        "queue closed",
                        MutationOutcomeStatus.FAILED_BEFORE_COMMIT,
                        False,
                    ),
                ],
            )
            self.assertEqual(batch.failed, 3)
            self.assertEqual(batch.succeeded, 0)

    def test_sql_queue_without_files_completes_immediately_with_rejections(self):
        rejected = import_args_use_case.RejectedProjectFileArg("x.txt", "bad")
        service = _startup_import_FakeImportService()
        use_case = import_args_use_case.ImportProjectFilesFromArgsUseCase(
            service,
            _startup_import_FakeProjectData("sql-database"),
            SimpleNamespace(file_entries=[]),
            SimpleNamespace(),
        )
        completed = []
        use_case.queue_imports(
            import_args_use_case.ProjectFileArgs(rejected=[rejected]),
            import_args_use_case.ProjectImportTarget("sql-database", "project-1"),
            completed.append,
        )
        self.assertEqual(len(completed), 1)
        self.assertEqual(completed[0].results, [])
        self.assertEqual(completed[0].rejected, [rejected])
        self.assertEqual(completed[0].failed, 1)
        self.assertEqual(completed[0].selected_project_uid, "project-1")
        self.assertEqual(service.queued_imports, [])

    def test_sql_startup_import_waits_for_uncertain_commit_recovery(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "source.ost"
            source.write_text("ost")
            service = _startup_import_FakeImportService()
            service.sql_collaboration = True
            target = import_args_use_case.ProjectImportTarget("sql-database")
            use_case = import_args_use_case.ImportProjectFilesFromArgsUseCase(
                service,
                _startup_import_FakeProjectData("sql-database"),
                SimpleNamespace(file_entries=[]),
                SimpleNamespace(),
            )
            completed = []
            use_case.queue_imports(
                _startup_import__project_file_args(source), target, completed.append
            )
            queued_callback = service.queued_imports[0][4]
            operation_id = str(uuid.uuid4())
            queued_callback(
                QueuedMutationResult(
                    database_id="sql-database",
                    runtime_generation=1,
                    operation_id=operation_id,
                    outcome_status=MutationOutcomeStatus.COMMIT_STATUS_UNKNOWN,
                )
            )
            self.assertEqual(completed, [])
            queued_callback(
                QueuedMutationResult(
                    database_id="sql-database",
                    runtime_generation=1,
                    operation_id=operation_id,
                    outcome_status=(MutationOutcomeStatus.COMMITTED_PROJECTION_FAILED),
                )
            )
            self.assertEqual(completed, [])
            queued_callback(
                QueuedMutationResult(
                    database_id="sql-database",
                    runtime_generation=1,
                    operation_id=operation_id,
                    outcome_status=MutationOutcomeStatus.COMMITTED,
                )
            )
            self.assertEqual(len(completed), 1)
            self.assertEqual(completed[0].succeeded, 1)
            self.assertEqual(
                completed[0].results[0].outcome_status,
                MutationOutcomeStatus.COMMITTED,
            )
            self.assertTrue(completed[0].results[0].success)
            self.assertEqual(completed[0].results[0].message, "Imported successfully.")
            self.assertEqual(completed[0].results[0].project_name, "source")
            queued_callback(
                QueuedMutationResult(
                    database_id="sql-database",
                    runtime_generation=1,
                    operation_id=operation_id,
                    outcome_status=MutationOutcomeStatus.CONFLICT,
                )
            )
            self.assertEqual(len(completed), 1)

    def test_sql_startup_import_terminal_failure_after_uncertain_status_is_reported(
        self,
    ):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "source.ost"
            source.write_text("ost")
            service = _startup_import_FakeImportService()
            use_case = import_args_use_case.ImportProjectFilesFromArgsUseCase(
                service,
                _startup_import_FakeProjectData("sql-database"),
                SimpleNamespace(file_entries=[]),
                SimpleNamespace(),
            )
            completed = []
            use_case.queue_imports(
                _startup_import__project_file_args(source),
                import_args_use_case.ProjectImportTarget("sql-database"),
                completed.append,
            )
            queued_callback = service.queued_imports[0][4]
            operation_id = str(uuid.uuid4())
            queued_callback(
                QueuedMutationResult(
                    database_id="sql-database",
                    runtime_generation=1,
                    operation_id=operation_id,
                    outcome_status=MutationOutcomeStatus.COMMIT_STATUS_UNKNOWN,
                )
            )
            self.assertEqual(completed, [])
            queued_callback(
                QueuedMutationResult(
                    database_id="sql-database",
                    runtime_generation=1,
                    operation_id=operation_id,
                    outcome_status=MutationOutcomeStatus.FAILED_BEFORE_COMMIT,
                )
            )
            self.assertEqual(len(completed), 1)
            result = completed[0].results[0]
            self.assertFalse(result.success)
            self.assertEqual(result.message, "The file could not be imported.")
            self.assertIsNone(result.project_name)
            self.assertEqual(
                result.outcome_status, MutationOutcomeStatus.FAILED_BEFORE_COMMIT
            )
            self.assertEqual(completed[0].failed, 1)

    def test_import_use_case_uses_stored_project_before_first_checked_fallback(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            first_db = root / "first.mdb"
            target_db = root / "target.mdb"
            source = root / "source.ost"
            first_db.write_text("db")
            target_db.write_text("db")
            source.write_text("ost")
            workspace = WorkspaceState()
            workspace.project_workspace.selected_node = ProjectTreeSelectionState(
                kind=WORKSPACE_NODE_KIND_PROJECT,
                file_path=str(target_db),
                project_uid="stored-project",
            )
            import_service = _startup_import_FakeImportService()
            use_case = import_args_use_case.ImportProjectFilesFromArgsUseCase(
                import_service=import_service,
                project_data_service=_startup_import_FakeProjectData(str(target_db)),
                file_state_model=SimpleNamespace(
                    file_entries=[
                        FileEntry(str(first_db), is_checked=True),
                        FileEntry(str(target_db), is_checked=True),
                    ]
                ),
                workspace_state_model=SimpleNamespace(state=workspace),
            )
            result = use_case.execute(
                parse_project_file_args([str(source)]), lambda _path: True
            )
            self.assertEqual(result.succeeded, 1)
            self.assertEqual(import_service.calls[0][0], "ost")
            self.assertEqual(import_service.calls[0][1], str(source.resolve()))
            self.assertEqual(import_service.calls[0][2], str(target_db))
            self.assertEqual(import_service.calls[0][3], "stored-project")
            self.assertIs(import_service.calls[0][4], False)
            self.assertEqual(import_service.reloads, [str(target_db)])
            self.assertEqual(result.target_db_path, str(target_db))
            self.assertEqual(result.selected_project_uid, "stored-project")
            self.assertEqual(result.results[0].project_name, "Stored Project")
            self.assertFalse(result.import_as_orphaned_due_to_deleted_target)

    def test_import_use_case_resolves_stored_bid_to_project_target(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target_db = root / "target.mdb"
            source = root / "source.ost"
            target_db.write_text("db")
            source.write_text("ost")
            workspace = WorkspaceState()
            workspace.project_workspace.selected_node = ProjectTreeSelectionState(
                kind=WORKSPACE_NODE_KIND_BID,
                file_path=str(target_db),
                bid_uid="stored-bid",
            )
            import_service = _startup_import_FakeImportService()
            use_case = import_args_use_case.ImportProjectFilesFromArgsUseCase(
                import_service=import_service,
                project_data_service=_startup_import_FakeProjectData(str(target_db)),
                file_state_model=SimpleNamespace(
                    file_entries=[FileEntry(str(target_db), is_checked=True)]
                ),
                workspace_state_model=SimpleNamespace(state=workspace),
            )
            result = use_case.execute(
                parse_project_file_args([str(source)]), lambda _path: True
            )
            self.assertEqual(import_service.calls[0][2], str(target_db))
            self.assertEqual(import_service.calls[0][3], "stored-project")
            self.assertEqual(result.selected_project_uid, "stored-project")

    def test_import_use_case_workspace_bid_without_known_project_imports_unassigned(
        self,
    ):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target_db = root / "target.mdb"
            source = root / "source.ost"
            target_db.write_text("db")
            source.write_text("ost")
            workspace = WorkspaceState()
            workspace.project_workspace.selected_node = ProjectTreeSelectionState(
                kind=WORKSPACE_NODE_KIND_BID,
                file_path=str(target_db),
                bid_uid="unknown-bid",
            )
            import_service = _startup_import_FakeImportService()
            use_case = import_args_use_case.ImportProjectFilesFromArgsUseCase(
                import_service=import_service,
                project_data_service=_startup_import_FakeProjectData(str(target_db)),
                file_state_model=SimpleNamespace(
                    file_entries=[FileEntry(str(target_db), is_checked=True)]
                ),
                workspace_state_model=SimpleNamespace(state=workspace),
            )
            result = use_case.execute(
                parse_project_file_args([str(source)]), lambda _path: True
            )
            self.assertEqual(result.succeeded, 1)
            self.assertEqual(import_service.calls[0][2], str(target_db))
            self.assertIsNone(import_service.calls[0][3])
            self.assertFalse(result.import_as_orphaned_due_to_deleted_target)

    def test_import_use_case_imports_deleted_bids_project_target_as_orphaned(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target_db = root / "target.mdb"
            source = root / "source.ost"
            target_db.write_text("db")
            source.write_text("ost")
            workspace = WorkspaceState()
            workspace.project_workspace.selected_node = ProjectTreeSelectionState(
                kind=WORKSPACE_NODE_KIND_PROJECT,
                file_path=str(target_db),
                project_uid=DELETED_BIDS_PROJECT_UID,
            )
            project_data = _startup_import_FakeProjectData(str(target_db))
            import_service = _startup_import_FakeImportService(
                project_data, "new-project"
            )
            use_case = import_args_use_case.ImportProjectFilesFromArgsUseCase(
                import_service=import_service,
                project_data_service=project_data,
                file_state_model=SimpleNamespace(
                    file_entries=[FileEntry(str(target_db), is_checked=True)]
                ),
                workspace_state_model=SimpleNamespace(state=workspace),
            )
            result = use_case.execute(
                parse_project_file_args([str(source)]), lambda _path: True
            )
            self.assertEqual(result.succeeded, 1)
            self.assertEqual(import_service.calls[0][2], str(target_db))
            self.assertIsNone(import_service.calls[0][3])
            self.assertTrue(result.import_as_orphaned_due_to_deleted_target)
            self.assertIsNone(result.selected_project_uid)
            self.assertEqual(import_service.reloads, [str(target_db)])

    def test_import_use_case_imports_deleted_bids_bid_target_as_orphaned(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target_db = root / "target.mdb"
            source = root / "source.ost"
            target_db.write_text("db")
            source.write_text("ost")
            workspace = WorkspaceState()
            workspace.project_workspace.selected_node = ProjectTreeSelectionState(
                kind=WORKSPACE_NODE_KIND_BID,
                file_path=str(target_db),
                bid_uid="deleted-bid",
            )
            project_data = _startup_import_FakeProjectData(str(target_db))
            project_data.hierarchy.loaded_files[0].bid_projects[
                DELETED_BIDS_PROJECT_UID
            ] = HierarchyProjectInfo(
                name=DELETED_BIDS_PROJECT_NAME,
                bids=[HierarchyBidInfo(uid="deleted-bid")],
            )
            import_service = _startup_import_FakeImportService(
                project_data, "new-project"
            )
            use_case = import_args_use_case.ImportProjectFilesFromArgsUseCase(
                import_service=import_service,
                project_data_service=project_data,
                file_state_model=SimpleNamespace(
                    file_entries=[FileEntry(str(target_db), is_checked=True)]
                ),
                workspace_state_model=SimpleNamespace(state=workspace),
            )
            result = use_case.execute(
                parse_project_file_args([str(source)]), lambda _path: True
            )
            self.assertEqual(result.succeeded, 1)
            self.assertEqual(import_service.calls[0][2], str(target_db))
            self.assertIsNone(import_service.calls[0][3])
            self.assertTrue(result.import_as_orphaned_due_to_deleted_target)
            self.assertIsNone(result.selected_project_uid)

    def test_import_use_case_imports_multiple_files_sequentially(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target_db = root / "target.mdb"
            ost = root / "source.ost"
            osp = root / "source.osp"
            target_db.write_text("db")
            ost.write_text("ost")
            osp.write_text("osp")
            import_service = _startup_import_FakeImportService()
            use_case = import_args_use_case.ImportProjectFilesFromArgsUseCase(
                import_service=import_service,
                project_data_service=_startup_import_FakeProjectData(str(target_db)),
                file_state_model=SimpleNamespace(
                    file_entries=[FileEntry(str(target_db), is_checked=True)]
                ),
                workspace_state_model=SimpleNamespace(state=WorkspaceState()),
            )
            result = use_case.execute(
                parse_project_file_args([str(ost), str(osp)]), lambda _path: True
            )
            self.assertEqual(result.succeeded, 2)
            self.assertEqual(result.failed, 0)
            self.assertEqual([call[0] for call in import_service.calls], ["ost", "osp"])
            self.assertEqual(
                [call[1] for call in import_service.calls],
                [str(ost.resolve()), str(osp.resolve())],
            )
            self.assertEqual([call[4] for call in import_service.calls], [False, False])
            self.assertEqual(import_service.reloads, [str(target_db)])
            self.assertEqual(
                [item.project_name for item in result.results], ["source", "source"]
            )
            self.assertFalse(result.refresh_pending)

    def test_import_use_case_individual_failures_do_not_stop_later_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target_db = root / "target.mdb"
            first = root / "first.ost"
            second = root / "second.osp"
            third = root / "third.ost"
            for path in (target_db, first, second, third):
                path.write_text("data")

            class FailingService(_startup_import_FakeImportService):
                def import_ost(self, source, target_db, project_uid, refresh=True):
                    if source.endswith("first.ost"):
                        raise RuntimeError("corrupt ost")
                    return super().import_ost(source, target_db, project_uid, refresh)

            import_service = FailingService()
            args = parse_project_file_args([str(first), str(second), str(third)])
            second.unlink()
            use_case = import_args_use_case.ImportProjectFilesFromArgsUseCase(
                import_service=import_service,
                project_data_service=_startup_import_FakeProjectData(str(target_db)),
                file_state_model=SimpleNamespace(
                    file_entries=[FileEntry(str(target_db), is_checked=True)]
                ),
                workspace_state_model=SimpleNamespace(state=WorkspaceState()),
                logger=_quiet_logger(),
            )
            result = use_case.execute(args, lambda _path: True)
            self.assertEqual(
                [(item.success, item.message) for item in result.results],
                [
                    (False, "corrupt ost"),
                    (False, "File does not exist."),
                    (True, "Imported successfully."),
                ],
            )
            self.assertEqual([call[0] for call in import_service.calls], ["ost"])
            self.assertEqual(result.succeeded, 1)
            self.assertEqual(result.failed, 2)
            self.assertEqual(import_service.reloads, [str(target_db)])
            self.assertEqual(result.results[2].project_name, "third")

    def test_import_use_case_service_refusal_is_reported_without_refresh(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target_db = root / "target.mdb"
            source = root / "source.osp"
            target_db.write_text("db")
            source.write_text("osp")

            class RefusingService(_startup_import_FakeImportService):
                def import_osp(self, source, target_db, project_uid, refresh=True):
                    super().import_osp(source, target_db, project_uid, refresh)
                    return False

            import_service = RefusingService()
            use_case = import_args_use_case.ImportProjectFilesFromArgsUseCase(
                import_service=import_service,
                project_data_service=_startup_import_FakeProjectData(str(target_db)),
                file_state_model=SimpleNamespace(
                    file_entries=[FileEntry(str(target_db), is_checked=True)]
                ),
                workspace_state_model=SimpleNamespace(state=WorkspaceState()),
            )
            result = use_case.execute(
                parse_project_file_args([str(source)]), lambda _path: True
            )
            self.assertEqual(len(import_service.calls), 1)
            self.assertEqual(result.succeeded, 0)
            self.assertEqual(result.failed, 1)
            self.assertEqual(
                result.results[0].message, "The file could not be imported."
            )
            self.assertEqual(import_service.reloads, [])
            self.assertFalse(result.refresh_pending)

    def test_import_use_case_can_defer_refresh_until_requested(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target_db = root / "target.mdb"
            source = root / "source.ost"
            target_db.write_text("db")
            source.write_text("ost")
            project_data = _startup_import_FakeProjectData(str(target_db))
            import_service = _startup_import_FakeImportService(
                project_data, "new-project"
            )
            use_case = import_args_use_case.ImportProjectFilesFromArgsUseCase(
                import_service=import_service,
                project_data_service=project_data,
                file_state_model=SimpleNamespace(
                    file_entries=[FileEntry(str(target_db), is_checked=True)]
                ),
                workspace_state_model=SimpleNamespace(state=WorkspaceState()),
            )
            deferred = use_case.execute(
                parse_project_file_args([str(source)]),
                lambda _path: True,
                refresh_after_import=False,
            )
            self.assertTrue(deferred.refresh_pending)
            self.assertEqual(import_service.reloads, [])
            self.assertIsNone(deferred.selected_project_uid)
            self.assertEqual(deferred.project_uids_before, {"stored-project"})
            refreshed = use_case.refresh_import_result(deferred)
            self.assertFalse(refreshed.refresh_pending)
            self.assertEqual(import_service.reloads, [str(target_db)])
            self.assertEqual(refreshed.selected_project_uid, "new-project")
            self.assertEqual(refreshed.results[0].project_name, "Imported Project")
            self.assertIs(use_case.refresh_import_result(refreshed), refreshed)
            self.assertEqual(import_service.reloads, [str(target_db)])

    def test_import_use_case_reports_missing_enabled_database(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "source.osp"
            source.write_text("osp")
            existing_db = Path(tmp) / "existing.mdb"
            existing_db.write_text("db")
            unavailable_entry_sets = {
                "no_entries": [],
                "missing_file": [FileEntry(str(Path(tmp) / "missing.mdb"))],
                "unchecked_file": [FileEntry(str(existing_db), is_checked=False)],
            }
            for label, entries in unavailable_entry_sets.items():
                with self.subTest(label=label):
                    import_service = _startup_import_FakeImportService()
                    flushed = []
                    use_case = import_args_use_case.ImportProjectFilesFromArgsUseCase(
                        import_service=import_service,
                        project_data_service=_startup_import_FakeProjectData(
                            str(Path(tmp) / "missing.mdb")
                        ),
                        file_state_model=SimpleNamespace(file_entries=entries),
                        workspace_state_model=SimpleNamespace(state=WorkspaceState()),
                    )
                    result = use_case.execute(
                        parse_project_file_args([str(source), "notes.txt"]),
                        lambda path: flushed.append(path) or True,
                    )
                    self.assertEqual(result.succeeded, 0)
                    self.assertEqual(result.failed, 2)
                    self.assertEqual(len(result.results), 1)
                    self.assertEqual(len(result.rejected), 1)
                    self.assertEqual(
                        result.results[0].source_path, str(source.resolve())
                    )
                    self.assertIn(
                        "Enable or store a database", result.results[0].message
                    )
                    self.assertIsNone(result.target_db_path)
                    self.assertEqual(flushed, [])
                    self.assertEqual(import_service.calls, [])
                    self.assertEqual(import_service.reloads, [])

    def test_import_use_case_flush_failure_prevents_import(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target_db = root / "target.mdb"
            source = root / "source.ost"
            target_db.write_text("db")
            source.write_text("ost")
            import_service = _startup_import_FakeImportService()
            use_case = import_args_use_case.ImportProjectFilesFromArgsUseCase(
                import_service=import_service,
                project_data_service=_startup_import_FakeProjectData(str(target_db)),
                file_state_model=SimpleNamespace(
                    file_entries=[FileEntry(str(target_db), is_checked=True)]
                ),
                workspace_state_model=SimpleNamespace(state=WorkspaceState()),
            )
            flushed = []
            result = use_case.execute(
                parse_project_file_args([str(source)]),
                lambda path: flushed.append(path) or False,
            )
            self.assertEqual(flushed, [str(target_db)])
            self.assertEqual(result.failed, 1)
            self.assertEqual(result.succeeded, 0)
            self.assertEqual(import_service.calls, [])
            self.assertEqual(import_service.reloads, [])
            self.assertEqual(result.target_db_path, str(target_db))
            self.assertEqual(
                result.results[0].message,
                "Pending database changes could not be saved before import.",
            )

    def test_import_use_case_reports_refresh_failure_after_import(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target_db = root / "target.mdb"
            source = root / "source.ost"
            target_db.write_text("db")
            source.write_text("ost")
            import_service = _startup_import_FakeImportService(reload_result=False)
            use_case = import_args_use_case.ImportProjectFilesFromArgsUseCase(
                import_service=import_service,
                project_data_service=_startup_import_FakeProjectData(str(target_db)),
                file_state_model=SimpleNamespace(
                    file_entries=[FileEntry(str(target_db), is_checked=True)]
                ),
                workspace_state_model=SimpleNamespace(state=WorkspaceState()),
            )
            result = use_case.execute(
                parse_project_file_args([str(source)]), lambda _path: True
            )
            self.assertEqual(len(import_service.calls), 1)
            self.assertEqual(import_service.reloads, [str(target_db)])
            self.assertEqual(result.failed, 1)
            self.assertEqual(result.succeeded, 0)
            self.assertFalse(result.refresh_pending)
            self.assertFalse(result.results[0].success)
            self.assertEqual(
                result.results[0].message,
                "Imported, but the database could not be refreshed. Reopen the "
                "database to see the imported project.",
            )

    def test_import_use_case_prefers_current_target(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            first_db = root / "first.mdb"
            current_db = root / "current.mdb"
            source = root / "source.osp"
            first_db.write_text("db")
            current_db.write_text("db")
            source.write_text("osp")
            import_service = _startup_import_FakeImportService()
            use_case = import_args_use_case.ImportProjectFilesFromArgsUseCase(
                import_service=import_service,
                project_data_service=_startup_import_FakeProjectData(str(current_db)),
                file_state_model=SimpleNamespace(
                    file_entries=[
                        FileEntry(str(first_db), is_checked=True),
                        FileEntry(str(current_db), is_checked=True),
                    ]
                ),
                workspace_state_model=SimpleNamespace(state=WorkspaceState()),
            )
            flushed = []
            result = use_case.execute(
                parse_project_file_args([str(source)]),
                lambda path: flushed.append(path) or True,
                current_target=import_args_use_case.ProjectImportCurrentTarget(
                    file_path=str(current_db), project_uid="current-project"
                ),
            )
            self.assertEqual(import_service.calls[0][2], str(current_db))
            self.assertEqual(import_service.calls[0][3], "current-project")
            self.assertEqual(flushed, [str(current_db)])
            self.assertEqual(result.target_db_path, str(current_db))
            self.assertEqual(result.selected_project_uid, "current-project")

    def test_import_use_case_unavailable_current_target_falls_back_to_first_checked(
        self,
    ):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            first_db = root / "first.mdb"
            unchecked_db = root / "unchecked.mdb"
            first_db.write_text("db")
            unchecked_db.write_text("db")
            use_case = import_args_use_case.ImportProjectFilesFromArgsUseCase(
                import_service=_startup_import_FakeImportService(),
                project_data_service=_startup_import_FakeProjectData(str(first_db)),
                file_state_model=SimpleNamespace(
                    file_entries=[
                        FileEntry(str(first_db), is_checked=True),
                        FileEntry(str(unchecked_db), is_checked=False),
                    ]
                ),
                workspace_state_model=SimpleNamespace(state=WorkspaceState()),
            )
            for label, current_path in (
                ("unchecked", str(unchecked_db)),
                ("not_stored", str(root / "other.mdb")),
                ("no_path", None),
            ):
                with self.subTest(label=label):
                    target = use_case.resolve_target(
                        import_args_use_case.ProjectImportCurrentTarget(
                            file_path=current_path, project_uid="current-project"
                        )
                    )
                    self.assertEqual(
                        target,
                        import_args_use_case.ProjectImportTarget(
                            file_path=str(first_db)
                        ),
                    )
            self.assertEqual(
                use_case.resolve_target(None),
                import_args_use_case.ProjectImportTarget(file_path=str(first_db)),
            )

    def test_import_use_case_current_deleted_bids_target_imports_as_orphaned(self):
        with tempfile.TemporaryDirectory() as tmp:
            current_db = Path(tmp) / "current.mdb"
            current_db.write_text("db")
            use_case = import_args_use_case.ImportProjectFilesFromArgsUseCase(
                import_service=_startup_import_FakeImportService(),
                project_data_service=_startup_import_FakeProjectData(str(current_db)),
                file_state_model=SimpleNamespace(
                    file_entries=[FileEntry(str(current_db), is_checked=True)]
                ),
                workspace_state_model=SimpleNamespace(state=WorkspaceState()),
            )
            target = use_case.resolve_target(
                import_args_use_case.ProjectImportCurrentTarget(
                    file_path=str(current_db), project_uid=DELETED_BIDS_PROJECT_UID
                )
            )
            self.assertEqual(
                target,
                import_args_use_case.ProjectImportTarget(
                    file_path=str(current_db),
                    project_uid=None,
                    import_as_orphaned_due_to_deleted_target=True,
                ),
            )

    def test_import_use_case_accepts_checked_sql_database_as_current_target(self):
        descriptor = DatabaseDescriptor.for_sql_server(
            SqlServerDatabaseLocation(
                server="localhost",
                database="OSTV_TEST",
                database_guid="00000000-0000-0000-0000-000000000111",
            ),
            schema_version=SQL_SCHEMA_V1.version,
        )
        use_case = import_args_use_case.ImportProjectFilesFromArgsUseCase(
            import_service=_startup_import_FakeImportService(),
            project_data_service=_startup_import_FakeProjectData(
                descriptor.database_id
            ),
            file_state_model=SimpleNamespace(
                file_entries=[FileEntry.for_descriptor(descriptor)]
            ),
            workspace_state_model=SimpleNamespace(state=WorkspaceState()),
        )
        target = use_case.resolve_target(
            import_args_use_case.ProjectImportCurrentTarget(
                file_path=descriptor.database_id,
                project_uid="sql-project",
            )
        )
        self.assertEqual(
            target,
            import_args_use_case.ProjectImportTarget(
                file_path=descriptor.database_id,
                project_uid="sql-project",
            ),
        )
        self.assertFalse(use_case.uses_async_import(target))
        unchecked = import_args_use_case.ImportProjectFilesFromArgsUseCase(
            import_service=_startup_import_FakeImportService(),
            project_data_service=_startup_import_FakeProjectData(
                descriptor.database_id
            ),
            file_state_model=SimpleNamespace(
                file_entries=[FileEntry.for_descriptor(descriptor, is_checked=False)]
            ),
            workspace_state_model=SimpleNamespace(state=WorkspaceState()),
        )
        self.assertIsNone(
            unchecked.resolve_target(
                import_args_use_case.ProjectImportCurrentTarget(
                    file_path=descriptor.database_id, project_uid="sql-project"
                )
            )
        )

    def test_import_use_case_detects_single_new_project(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target_db = root / "target.mdb"
            source = root / "source.ost"
            target_db.write_text("db")
            source.write_text("ost")
            project_data = _startup_import_FakeProjectData(str(target_db))
            use_case = import_args_use_case.ImportProjectFilesFromArgsUseCase(
                import_service=_startup_import_FakeImportService(
                    project_data, "new-project"
                ),
                project_data_service=project_data,
                file_state_model=SimpleNamespace(
                    file_entries=[FileEntry(str(target_db), is_checked=True)]
                ),
                workspace_state_model=SimpleNamespace(state=WorkspaceState()),
            )
            result = use_case.execute(
                parse_project_file_args([str(source)]), lambda _path: True
            )
            self.assertEqual(result.selected_project_uid, "new-project")
            self.assertEqual(result.results[0].project_name, "Imported Project")
            self.assertEqual(result.project_uids_before, {"stored-project"})

    def test_import_use_case_does_not_guess_project_when_several_appear(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target_db = root / "target.mdb"
            ost = root / "first.ost"
            osp = root / "second.osp"
            for path in (target_db, ost, osp):
                path.write_text("data")
            project_data = _startup_import_FakeProjectData(str(target_db))

            class TwoProjectService(_startup_import_FakeImportService):
                def _add_project(self, target_db):
                    entry = self.project_data.hierarchy.loaded_files[0]
                    entry.bid_projects[f"new-{len(self.calls)}"] = HierarchyProjectInfo(
                        name=f"Imported {len(self.calls)}"
                    )

            import_service = TwoProjectService(project_data, "unused")
            use_case = import_args_use_case.ImportProjectFilesFromArgsUseCase(
                import_service=import_service,
                project_data_service=project_data,
                file_state_model=SimpleNamespace(
                    file_entries=[FileEntry(str(target_db), is_checked=True)]
                ),
                workspace_state_model=SimpleNamespace(state=WorkspaceState()),
            )
            result = use_case.execute(
                parse_project_file_args([str(ost), str(osp)]), lambda _path: True
            )
            self.assertEqual(result.succeeded, 2)
            self.assertIsNone(result.selected_project_uid)
            self.assertEqual(
                [item.project_name for item in result.results], ["first", "second"]
            )


import inspect as _second_pass_inspect
from ost_visualizer.application.services.import_service import (
    ImportService as _SecondPassImportService,
)
from ost_visualizer.domain.entities.workspace_state import (
    WORKSPACE_NODE_KIND_DATABASE,
)


class ImportProjectFilesFromArgsSecondPassTests(unittest.TestCase):
    """Second-pass coverage of the app-args import use case (file association CLI path;
    no registry is touched). Fakes: the startup-import fake import service (checked
    against the real ImportService signatures below), hierarchy stub and plain
    SimpleNamespace models. Access keeps its synchronous importer; the SQL queue path
    is driven by delivering the queued callbacks by hand."""

    @staticmethod
    def _use_case(
        service=None, project_data=None, entries=(), workspace=None, logger=None
    ):
        return import_args_use_case.ImportProjectFilesFromArgsUseCase(
            import_service=service or _startup_import_FakeImportService(),
            project_data_service=project_data
            or _startup_import_FakeProjectData("target.mdb"),
            file_state_model=SimpleNamespace(file_entries=list(entries)),
            workspace_state_model=SimpleNamespace(state=workspace or WorkspaceState()),
            logger=logger or _quiet_logger(),
        )

    @staticmethod
    def _result(status, message=""):
        return QueuedMutationResult(
            database_id="sql-database",
            runtime_generation=1,
            operation_id=str(uuid.uuid4()),
            outcome_status=status,
            message=message,
        )

    def test_the_fake_import_service_accepts_exactly_the_calls_the_real_one_does(self):
        shapes = {
            "import_ost": (("a.ost", "db", "p"), {"refresh": False}),
            "import_osp": (("a.osp", "db", None), {"refresh": False}),
            "queue_project_import": (("a.ost", "ost", "db", "p", print), {}),
            "uses_sql_collaboration_import": (("db",), {}),
            "reload_and_notify": (("db",), {}),
        }
        for name, (args, kwargs) in shapes.items():
            with self.subTest(name):
                for owner in (
                    _SecondPassImportService,
                    _startup_import_FakeImportService,
                ):
                    _second_pass_inspect.signature(getattr(owner, name)).bind(
                        None, *args, **kwargs
                    )

    def test_uses_async_import_asks_the_import_service_about_the_target_database(self):
        asked = []

        class Service(_startup_import_FakeImportService):
            def uses_sql_collaboration_import(self, target_db):
                asked.append(target_db)
                return target_db == "sql-database"

        use_case = self._use_case(Service())
        sql_target = import_args_use_case.ProjectImportTarget("sql-database")
        access_target = import_args_use_case.ProjectImportTarget("target.mdb")
        self.assertIs(use_case.uses_async_import(sql_target), True)
        self.assertIs(use_case.uses_async_import(access_target), False)
        self.assertEqual(asked, ["sql-database", "target.mdb"])

    def test_a_duplicate_completion_before_the_batch_is_done_does_not_finish_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            first = Path(tmp) / "first.ost"
            second = Path(tmp) / "second.osp"
            first.write_text("ost")
            second.write_text("osp")
            service = _startup_import_FakeImportService()
            use_case = self._use_case(service)
            completed = []
            use_case.queue_imports(
                _startup_import__project_file_args(first, second),
                import_args_use_case.ProjectImportTarget("sql-database"),
                completed.append,
            )
            committed = MutationOutcomeStatus.COMMITTED
            service.queued_imports[0][4](self._result(committed))
            service.queued_imports[0][4](self._result(MutationOutcomeStatus.CONFLICT))
            self.assertEqual(completed, [])
            service.queued_imports[1][4](self._result(committed))
            self.assertEqual(len(completed), 1)
            self.assertEqual(
                [result.outcome_status for result in completed[0].results],
                [committed, committed],
            )
            self.assertEqual(
                [result.success for result in completed[0].results], [True, True]
            )

    def test_a_rejected_queued_import_without_a_message_gets_the_default_text(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "source.ost"
            source.write_text("ost")
            for status, message, expected in (
                (MutationOutcomeStatus.REJECTED, "", "The file could not be imported."),
                (MutationOutcomeStatus.FAILED_BEFORE_COMMIT, "disk full", "disk full"),
                (
                    MutationOutcomeStatus.CANCELLED_BEFORE_START,
                    "",
                    "The file could not be imported.",
                ),
            ):
                with self.subTest(status=status):
                    service = _startup_import_FakeImportService()
                    completed = []
                    self._use_case(service).queue_imports(
                        _startup_import__project_file_args(source),
                        import_args_use_case.ProjectImportTarget("sql-database"),
                        completed.append,
                    )
                    service.queued_imports[0][4](self._result(status, message))
                    (result,) = completed[0].results
                    self.assertEqual(
                        (result.success, result.message, result.project_name),
                        (False, expected, None),
                    )
                    self.assertEqual(result.outcome_status, status)
                    self.assertEqual(result.source_path, str(source.resolve()))

    def test_a_queue_failure_without_a_message_is_logged_and_reported_by_default(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "source.ost"
            source.write_text("ost")

            class Service(_startup_import_FakeImportService):
                def queue_project_import(self, *args):
                    raise RuntimeError()

            logger = logging.getLogger("test.import_args.queue_failure")
            logger.propagate = False
            completed = []
            with self.assertLogs(logger, "ERROR") as logged:
                self._use_case(Service(), logger=logger).queue_imports(
                    _startup_import__project_file_args(source),
                    import_args_use_case.ProjectImportTarget("sql-database"),
                    completed.append,
                )
            self.assertEqual(len(logged.records), 1)
            self.assertIn(str(source.resolve()), logged.records[0].getMessage())
            self.assertIsNotNone(logged.records[0].exc_info)
            (result,) = completed[0].results
            self.assertEqual(
                (result.success, result.message, result.outcome_status),
                (
                    False,
                    "The file could not be queued.",
                    MutationOutcomeStatus.FAILED_BEFORE_COMMIT,
                ),
            )

    def test_queued_batches_report_every_missing_file_in_argument_order(self):
        with tempfile.TemporaryDirectory() as tmp:
            args = import_args_use_case.ProjectFileArgs(
                files=[
                    import_args_use_case.ParsedProjectFileArg(
                        str(Path(tmp) / name), PROJECT_IMPORT_EXTENSION_OST
                    )
                    for name in ("a.ost", "b.ost")
                ]
            )
            service = _startup_import_FakeImportService()
            completed = []
            target = import_args_use_case.ProjectImportTarget(
                "sql-database", import_as_orphaned_due_to_deleted_target=True
            )
            self._use_case(service).queue_imports(args, target, completed.append)
        self.assertEqual(len(completed), 1)
        batch = completed[0]
        self.assertEqual(
            [result.source_path for result in batch.results],
            [item.path for item in args.files],
        )
        self.assertEqual(batch.failed, 2)
        self.assertIs(batch.import_as_orphaned_due_to_deleted_target, True)
        self.assertEqual(
            (batch.target_db_path, batch.selected_project_uid), ("sql-database", None)
        )
        self.assertEqual(service.queued_imports, [])

    def test_an_access_import_failure_without_a_message_is_logged_and_defaulted(self):
        with tempfile.TemporaryDirectory() as tmp:
            target_db = Path(tmp) / "target.mdb"
            source = Path(tmp) / "source.ost"
            target_db.write_text("db")
            source.write_text("ost")

            class Service(_startup_import_FakeImportService):
                def import_ost(self, *args, **kwargs):
                    raise ValueError()

            logger = logging.getLogger("test.import_args.access_failure")
            logger.propagate = False
            use_case = self._use_case(
                Service(),
                entries=[FileEntry(str(target_db), is_checked=True)],
                logger=logger,
            )
            with self.assertLogs(logger, "ERROR") as logged:
                result = use_case.execute(
                    parse_project_file_args([str(source)]), lambda _path: True
                )
            self.assertEqual(len(logged.records), 1)
            self.assertIn(str(source.resolve()), logged.records[0].getMessage())
            (item,) = result.results
            self.assertEqual((item.success, item.message), (False, "Import failed."))
            self.assertEqual(result.failed, 1)

    def test_a_selected_project_survives_a_newly_created_project(self):
        with tempfile.TemporaryDirectory() as tmp:
            target_db = Path(tmp) / "target.mdb"
            source = Path(tmp) / "source.ost"
            target_db.write_text("db")
            source.write_text("ost")
            project_data = _startup_import_FakeProjectData(str(target_db))
            service = _startup_import_FakeImportService(project_data, "new-project")
            use_case = self._use_case(
                service,
                project_data,
                entries=[FileEntry(str(target_db), is_checked=True)],
            )
            result = use_case.execute(
                parse_project_file_args([str(source)]),
                lambda _path: True,
                current_target=import_args_use_case.ProjectImportCurrentTarget(
                    file_path=str(target_db), project_uid="stored-project"
                ),
            )
            self.assertEqual(result.selected_project_uid, "stored-project")
            self.assertEqual(result.results[0].project_name, "Stored Project")
            self.assertEqual(service.calls[0][3], "stored-project")

    def test_a_single_import_keeps_its_file_name_when_no_project_is_known(self):
        with tempfile.TemporaryDirectory() as tmp:
            target_db = Path(tmp) / "target.mdb"
            source = Path(tmp) / "source.ost"
            target_db.write_text("db")
            source.write_text("ost")
            use_case = self._use_case(
                entries=[FileEntry(str(target_db), is_checked=True)],
                project_data=_startup_import_FakeProjectData(str(target_db)),
            )
            result = use_case.execute(
                parse_project_file_args([str(source)]), lambda _path: True
            )
            self.assertIsNone(result.selected_project_uid)
            self.assertEqual(result.results[0].project_name, "source")
            self.assertTrue(result.results[0].success)

    def test_a_batch_without_a_database_path_only_clears_its_pending_refresh(self):
        service = _startup_import_FakeImportService()
        use_case = self._use_case(service)
        pending = import_args_use_case.ProjectFileImportBatchResult(
            results=[
                import_args_use_case.ProjectFileImportResult("a.ost", True, "ok", "a")
            ],
            refresh_pending=True,
        )
        refreshed = use_case.refresh_import_result(pending)
        self.assertIs(refreshed.refresh_pending, False)
        self.assertEqual(refreshed.results, pending.results)
        self.assertEqual(service.reloads, [])
        idle = import_args_use_case.ProjectFileImportBatchResult(
            target_db_path="target.mdb"
        )
        self.assertIs(use_case.refresh_import_result(idle), idle)
        self.assertEqual(service.reloads, [])

    def test_a_flush_failure_keeps_the_orphan_flag_and_selected_project_of_the_target(
        self,
    ):
        with tempfile.TemporaryDirectory() as tmp:
            target_db = Path(tmp) / "target.mdb"
            source = Path(tmp) / "source.ost"
            target_db.write_text("db")
            source.write_text("ost")
            service = _startup_import_FakeImportService()
            use_case = self._use_case(
                service, entries=[FileEntry(str(target_db), is_checked=True)]
            )
            result = use_case.execute(
                parse_project_file_args([str(source), "notes.txt"]),
                lambda _path: False,
                current_target=import_args_use_case.ProjectImportCurrentTarget(
                    file_path=str(target_db), project_uid=DELETED_BIDS_PROJECT_UID
                ),
            )
            self.assertIs(result.import_as_orphaned_due_to_deleted_target, True)
            self.assertIsNone(result.selected_project_uid)
            self.assertEqual(result.target_db_path, str(target_db))
            self.assertEqual(len(result.rejected), 1)
            self.assertEqual(result.failed, 2)
            self.assertEqual(service.calls, [])
            kept = use_case.execute(
                parse_project_file_args([str(source)]),
                lambda _path: False,
                current_target=import_args_use_case.ProjectImportCurrentTarget(
                    file_path=str(target_db), project_uid="kept-project"
                ),
            )
            self.assertEqual(kept.selected_project_uid, "kept-project")
            self.assertIs(kept.import_as_orphaned_due_to_deleted_target, False)

    def test_no_enabled_database_result_has_no_target_and_keeps_the_rejections(self):
        rejected = import_args_use_case.RejectedProjectFileArg("x.txt", "bad")
        args = import_args_use_case.ProjectFileArgs(
            files=[import_args_use_case.ParsedProjectFileArg("a.ost", ".ost")],
            rejected=[rejected],
        )
        result = self._use_case().build_no_target_result(args)
        self.assertEqual(result.rejected, [rejected])
        self.assertIsNone(result.target_db_path)
        self.assertIsNone(result.selected_project_uid)
        self.assertIs(result.refresh_pending, False)
        self.assertEqual(
            [(item.source_path, item.success) for item in result.results],
            [("a.ost", False)],
        )

    def test_a_missing_database_file_is_skipped_for_the_next_enabled_one(self):
        with tempfile.TemporaryDirectory() as tmp:
            missing = Path(tmp) / "missing.mdb"
            present = Path(tmp) / "present.mdb"
            unchecked = Path(tmp) / "unchecked.mdb"
            present.write_text("db")
            unchecked.write_text("db")
            use_case = self._use_case(
                entries=[
                    FileEntry(str(missing), is_checked=True),
                    FileEntry(str(unchecked), is_checked=False),
                    FileEntry(str(present), is_checked=True),
                ]
            )
            self.assertEqual(
                use_case.resolve_target(None),
                import_args_use_case.ProjectImportTarget(file_path=str(present)),
            )
            self.assertEqual(
                use_case.resolve_target(
                    import_args_use_case.ProjectImportCurrentTarget(
                        file_path=str(missing), project_uid="p"
                    )
                ),
                import_args_use_case.ProjectImportTarget(file_path=str(present)),
            )

    def test_the_workspace_selection_decides_the_project_by_node_kind(self):
        with tempfile.TemporaryDirectory() as tmp:
            first = Path(tmp) / "first.mdb"
            second = Path(tmp) / "second.mdb"
            for path in (first, second):
                path.write_text("db")
            entries = [
                FileEntry(str(first), is_checked=True),
                FileEntry(str(second), is_checked=True),
            ]
            project_data = _startup_import_FakeProjectData(str(second))
            cases = (
                (
                    "database node ignores a stale project uid",
                    ProjectTreeSelectionState(
                        kind=WORKSPACE_NODE_KIND_DATABASE,
                        file_path=str(second),
                        project_uid="stale-project",
                    ),
                    import_args_use_case.ProjectImportTarget(str(second)),
                ),
                (
                    "project node keeps its project",
                    ProjectTreeSelectionState(
                        kind=WORKSPACE_NODE_KIND_PROJECT,
                        file_path=str(second),
                        project_uid="stored-project",
                    ),
                    import_args_use_case.ProjectImportTarget(
                        str(second), "stored-project"
                    ),
                ),
                (
                    "bid node resolves its project",
                    ProjectTreeSelectionState(
                        kind=WORKSPACE_NODE_KIND_BID,
                        file_path=str(second),
                        bid_uid="stored-bid",
                    ),
                    import_args_use_case.ProjectImportTarget(
                        str(second), "stored-project"
                    ),
                ),
                (
                    "unchecked database falls back to the first enabled one",
                    ProjectTreeSelectionState(
                        kind=WORKSPACE_NODE_KIND_PROJECT,
                        file_path=str(Path(tmp) / "other.mdb"),
                        project_uid="stored-project",
                    ),
                    import_args_use_case.ProjectImportTarget(str(first)),
                ),
            )
            for label, selected, expected in cases:
                with self.subTest(label):
                    workspace = WorkspaceState()
                    workspace.project_workspace.selected_node = selected
                    use_case = self._use_case(
                        project_data=project_data, entries=entries, workspace=workspace
                    )
                    self.assertEqual(use_case.resolve_target(None), expected)

    def test_the_bid_to_project_lookup_matches_the_database_and_the_bid_exactly(self):
        with tempfile.TemporaryDirectory() as tmp:
            first = Path(tmp) / "first.mdb"
            second = Path(tmp) / "second.mdb"
            for path in (first, second):
                path.write_text("db")
            project_data = _startup_import_FakeProjectData(str(first))
            project_data.hierarchy.loaded_files.append(
                HierarchyFileEntry(
                    file_path=str(second),
                    bid_projects={
                        "other-project": HierarchyProjectInfo(
                            name="Other", bids=[HierarchyBidInfo(uid="other-bid")]
                        ),
                        "second-project": HierarchyProjectInfo(
                            name="Second",
                            bids=[
                                HierarchyBidInfo(uid="x"),
                                HierarchyBidInfo(uid="wanted-bid"),
                            ],
                        ),
                    },
                )
            )
            use_case = self._use_case(project_data=project_data)
            self.assertEqual(
                use_case._project_uid_for_bid(str(second), "wanted-bid"),
                "second-project",
            )
            self.assertIsNone(use_case._project_uid_for_bid(str(first), "wanted-bid"))
            self.assertIsNone(use_case._project_uid_for_bid(str(second), "missing"))
            self.assertEqual(
                use_case._project_uids_for_file(str(second)),
                {"other-project", "second-project"},
            )
            self.assertEqual(use_case._project_uids_for_file("elsewhere.mdb"), set())
            self.assertEqual(
                use_case._project_name(str(second), "second-project"), "Second"
            )
            self.assertIsNone(use_case._project_name(str(second), "stored-project"))
            self.assertIsNone(use_case._project_name(str(second), ""))
            self.assertIsNone(use_case._project_name("elsewhere.mdb", "second-project"))

    def test_a_new_project_is_only_detected_when_exactly_one_appeared(self):
        project_data = _startup_import_FakeProjectData("target.mdb")
        use_case = self._use_case(project_data=project_data)
        entry = project_data.hierarchy.loaded_files[0]
        self.assertIsNone(
            use_case._detect_new_project_uid("target.mdb", ["stored-project"])
        )
        entry.bid_projects["new-b"] = HierarchyProjectInfo(name="B")
        self.assertEqual(
            use_case._detect_new_project_uid("target.mdb", ["stored-project"]), "new-b"
        )
        entry.bid_projects["new-a"] = HierarchyProjectInfo(name="A")
        self.assertIsNone(
            use_case._detect_new_project_uid("target.mdb", ["stored-project"])
        )
        self.assertEqual(
            use_case._detect_new_project_uid("target.mdb", ["stored-project", "new-a"]),
            "new-b",
        )
        self.assertEqual(
            use_case._detect_new_project_uid("TARGET.mdb", {"stored-project", "new-b"}),
            "new-a",
        )

    def test_a_deferred_batch_with_only_failures_never_reloads_the_database(self):
        with tempfile.TemporaryDirectory() as tmp:
            target_db = Path(tmp) / "target.mdb"
            target_db.write_text("db")
            service = _startup_import_FakeImportService()
            use_case = self._use_case(
                service, entries=[FileEntry(str(target_db), is_checked=True)]
            )
            missing = Path(tmp) / "missing.ost"
            args = import_args_use_case.ProjectFileArgs(
                files=[
                    import_args_use_case.ParsedProjectFileArg(
                        str(missing), PROJECT_IMPORT_EXTENSION_OST
                    )
                ]
            )
            batch = use_case.execute(
                args, lambda _path: True, refresh_after_import=False
            )
            self.assertIs(batch.refresh_pending, False)
            self.assertEqual(service.reloads, [])
            self.assertEqual(batch.results[0].message, "File does not exist.")
            self.assertIsNone(batch.results[0].outcome_status)

    def test_the_result_value_objects_are_immutable_and_default_to_empty(self):
        import dataclasses

        values = (
            import_args_use_case.ProjectImportCurrentTarget(),
            import_args_use_case.ProjectImportTarget("db"),
            import_args_use_case.ProjectFileImportResult("a.ost", True, "ok"),
            import_args_use_case.ProjectFileImportBatchResult(),
        )
        for value in values:
            with self.subTest(type(value).__name__):
                field = dataclasses.fields(value)[0].name
                with self.assertRaises(dataclasses.FrozenInstanceError):
                    setattr(value, field, "changed")
        target = import_args_use_case.ProjectImportTarget("db")
        self.assertEqual(
            (target.project_uid, target.import_as_orphaned_due_to_deleted_target),
            (None, False),
        )
        item = import_args_use_case.ProjectFileImportResult("a.ost", True, "ok")
        self.assertEqual((item.project_name, item.outcome_status), (None, None))
        batch = import_args_use_case.ProjectFileImportBatchResult()
        self.assertEqual(
            (
                batch.results,
                batch.rejected,
                batch.target_db_path,
                batch.selected_project_uid,
                batch.import_as_orphaned_due_to_deleted_target,
                batch.refresh_pending,
                batch.project_uids_before,
                batch.succeeded,
                batch.failed,
            ),
            ([], [], None, None, False, False, frozenset(), 0, 0),
        )

    def test_execute_imports_refreshes_by_default_and_only_after_a_success(self):
        with tempfile.TemporaryDirectory() as tmp:
            target_db = Path(tmp) / "target.mdb"
            source = Path(tmp) / "source.ost"
            target_db.write_text("db")
            source.write_text("ost")
            service = _startup_import_FakeImportService()
            use_case = self._use_case(
                service, entries=[FileEntry(str(target_db), is_checked=True)]
            )
            target = import_args_use_case.ProjectImportTarget(str(target_db))
            batch = use_case.execute_imports(
                parse_project_file_args([str(source)]), target
            )
            self.assertIs(batch.refresh_pending, False)
            self.assertEqual(service.reloads, [str(target_db)])
            service.reloads.clear()
            missing = import_args_use_case.ProjectFileArgs(
                files=[
                    import_args_use_case.ParsedProjectFileArg(
                        str(Path(tmp) / "missing.ost"), PROJECT_IMPORT_EXTENSION_OST
                    )
                ]
            )
            self.assertIs(
                use_case.execute_imports(missing, target).refresh_pending, False
            )
            self.assertEqual(service.reloads, [])

    def test_a_use_case_without_a_logger_logs_import_failures_to_its_module_logger(
        self,
    ):
        with tempfile.TemporaryDirectory() as tmp:
            target_db = Path(tmp) / "target.mdb"
            source = Path(tmp) / "source.ost"
            target_db.write_text("db")
            source.write_text("ost")

            class Service(_startup_import_FakeImportService):
                def import_ost(self, *args, **kwargs):
                    raise RuntimeError("corrupt")

            use_case = import_args_use_case.ImportProjectFilesFromArgsUseCase(
                Service(),
                _startup_import_FakeProjectData(str(target_db)),
                SimpleNamespace(
                    file_entries=[FileEntry(str(target_db), is_checked=True)]
                ),
                SimpleNamespace(state=WorkspaceState()),
            )
            with self.assertLogs(import_args_use_case.__name__, "ERROR") as logged:
                result = use_case.execute(
                    parse_project_file_args([str(source)]), lambda _path: True
                )
            self.assertEqual(len(logged.records), 1)
            self.assertEqual(result.results[0].message, "corrupt")

    def test_a_single_success_names_only_itself_when_another_file_failed(self):
        with tempfile.TemporaryDirectory() as tmp:
            target_db = Path(tmp) / "target.mdb"
            good = Path(tmp) / "good.ost"
            gone = Path(tmp) / "gone.ost"
            for path in (target_db, good, gone):
                path.write_text("data")
            args = parse_project_file_args([str(good), str(gone)])
            gone.unlink()
            use_case = self._use_case(
                project_data=_startup_import_FakeProjectData(str(target_db)),
                entries=[FileEntry(str(target_db), is_checked=True)],
            )
            result = use_case.execute(
                args,
                lambda _path: True,
                current_target=import_args_use_case.ProjectImportCurrentTarget(
                    file_path=str(target_db), project_uid="stored-project"
                ),
            )
            self.assertEqual(
                [(item.success, item.project_name) for item in result.results],
                [(True, "Stored Project"), (False, None)],
            )

    def test_the_selected_node_kind_wins_over_a_stale_bid_uid(self):
        with tempfile.TemporaryDirectory() as tmp:
            target_db = Path(tmp) / "target.mdb"
            target_db.write_text("db")
            entries = [FileEntry(str(target_db), is_checked=True)]
            project_data = _startup_import_FakeProjectData(str(target_db))
            project_data.hierarchy.loaded_files[0].bid_projects[""] = (
                HierarchyProjectInfo(name="Nameless", bids=[HierarchyBidInfo(uid="")])
            )
            cases = (
                (
                    "project node with a stale bid uid",
                    ProjectTreeSelectionState(
                        kind=WORKSPACE_NODE_KIND_PROJECT,
                        file_path=str(target_db),
                        project_uid="explicit-project",
                        bid_uid="stored-bid",
                    ),
                    "explicit-project",
                ),
                (
                    "bid node without a bid uid",
                    ProjectTreeSelectionState(
                        kind=WORKSPACE_NODE_KIND_BID,
                        file_path=str(target_db),
                        bid_uid="",
                    ),
                    None,
                ),
            )
            for label, selected, expected in cases:
                with self.subTest(label):
                    workspace = WorkspaceState()
                    workspace.project_workspace.selected_node = selected
                    use_case = self._use_case(
                        project_data=project_data, entries=entries, workspace=workspace
                    )
                    self.assertEqual(
                        use_case.resolve_target(None),
                        import_args_use_case.ProjectImportTarget(
                            str(target_db), expected
                        ),
                    )
            use_case = self._use_case(project_data=project_data)
            self.assertIsNone(use_case._project_name(str(target_db), ""))
