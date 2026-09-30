from __future__ import annotations
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

    def test_import_use_case_uses_stored_project_before_first_checked_fallback(self):
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
                project_uid="stored-project",
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
            self.assertEqual(import_service.calls[0][0], "ost")
            self.assertEqual(import_service.calls[0][2], str(target_db))
            self.assertEqual(import_service.calls[0][3], "stored-project")
            self.assertIs(import_service.calls[0][4], False)
            self.assertEqual(import_service.reloads, [str(target_db)])

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
            use_case.execute(parse_project_file_args([str(source)]), lambda _path: True)
            self.assertEqual(import_service.calls[0][3], "stored-project")

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
            self.assertIsNone(import_service.calls[0][3])
            self.assertTrue(result.import_as_orphaned_due_to_deleted_target)
            self.assertIsNone(result.selected_project_uid)

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
            import_service = _startup_import_FakeImportService()
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
            self.assertIsNone(import_service.calls[0][3])
            self.assertTrue(result.import_as_orphaned_due_to_deleted_target)

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
            self.assertEqual([call[0] for call in import_service.calls], ["ost", "osp"])
            self.assertEqual(import_service.reloads, [str(target_db)])

    def test_import_use_case_reports_missing_enabled_database(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "source.osp"
            source.write_text("osp")
            use_case = import_args_use_case.ImportProjectFilesFromArgsUseCase(
                import_service=_startup_import_FakeImportService(),
                project_data_service=_startup_import_FakeProjectData(
                    str(Path(tmp) / "missing.mdb")
                ),
                file_state_model=SimpleNamespace(file_entries=[]),
                workspace_state_model=SimpleNamespace(state=WorkspaceState()),
            )
            result = use_case.execute(
                parse_project_file_args([str(source)]), lambda _path: True
            )
            self.assertEqual(result.succeeded, 0)
            self.assertEqual(result.failed, 1)
            self.assertIn("Enable or store a database", result.results[0].message)

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
            result = use_case.execute(
                parse_project_file_args([str(source)]),
                lambda _path: False,
            )
            self.assertEqual(result.failed, 1)
            self.assertEqual(import_service.calls, [])
            self.assertIn("Pending database changes", result.results[0].message)

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
            self.assertEqual(result.failed, 1)
            self.assertIn("could not be refreshed", result.results[0].message)

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
            use_case.execute(
                parse_project_file_args([str(source)]),
                lambda _path: True,
                current_target=import_args_use_case.ProjectImportCurrentTarget(
                    file_path=str(current_db), project_uid="current-project"
                ),
            )
            self.assertEqual(import_service.calls[0][2], str(current_db))
            self.assertEqual(import_service.calls[0][3], "current-project")

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
