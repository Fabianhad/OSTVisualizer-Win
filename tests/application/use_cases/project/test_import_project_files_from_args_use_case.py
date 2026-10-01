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
