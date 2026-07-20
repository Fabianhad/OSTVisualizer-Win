from __future__ import annotations
import logging
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Callable, Iterable, List, Optional
from ....domain.entities.database_descriptor import DatabaseBackend
from ....domain.entities.file_state import normalize_path
from ....domain.entities.project_constants import is_deleted_bids_project_uid
from ....domain.entities.workspace_state import (
    WORKSPACE_NODE_KIND_BID,
    WORKSPACE_NODE_KIND_PROJECT,
)
from ...dtos.file_import_args import (
    PROJECT_IMPORT_EXTENSION_OST,
    ParsedProjectFileArg,
    ProjectFileArgs,
    RejectedProjectFileArg,
)


@dataclass(frozen=True)
class ProjectImportCurrentTarget:
    file_path: Optional[str] = None
    project_uid: Optional[str] = None


@dataclass(frozen=True)
class ProjectImportTarget:
    file_path: str
    project_uid: Optional[str] = None
    import_as_orphaned_due_to_deleted_target: bool = False


@dataclass(frozen=True)
class ProjectFileImportResult:
    source_path: str
    success: bool
    message: str
    project_name: Optional[str] = None


@dataclass(frozen=True)
class ProjectFileImportBatchResult:
    results: List[ProjectFileImportResult] = field(default_factory=list)
    rejected: List[RejectedProjectFileArg] = field(default_factory=list)
    target_db_path: Optional[str] = None
    selected_project_uid: Optional[str] = None
    import_as_orphaned_due_to_deleted_target: bool = False
    refresh_pending: bool = False
    project_uids_before: frozenset[str] = field(default_factory=frozenset)

    @property
    def succeeded(self) -> int:
        return sum(1 for result in self.results if result.success)

    @property
    def failed(self) -> int:
        return sum(1 for result in self.results if not result.success) + len(
            self.rejected
        )


class ImportProjectFilesFromArgsUseCase:
    def __init__(
        self,
        import_service,
        project_data_service,
        file_state_model,
        workspace_state_model,
        logger: Optional[logging.Logger] = None,
    ) -> None:
        self._import_service = import_service
        self._project_data = project_data_service
        self._file_state_model = file_state_model
        self._workspace_state_model = workspace_state_model
        self._logger = logger or logging.getLogger(__name__)

    def execute(
        self,
        args: ProjectFileArgs,
        flush_for_file: Callable[[str], bool],
        current_target: Optional[ProjectImportCurrentTarget] = None,
        refresh_after_import: bool = True,
    ) -> ProjectFileImportBatchResult:
        target = self.resolve_target(current_target)
        if target is None:
            return self.build_no_target_result(args)
        if not flush_for_file(target.file_path):
            return self.build_flush_failure_result(args, target)
        return self.execute_imports(
            args, target, refresh_after_import=refresh_after_import
        )

    def build_no_target_result(
        self, args: ProjectFileArgs
    ) -> ProjectFileImportBatchResult:
        message = (
            "No enabled database is available. Enable or store a database before "
            "importing .ost or .osp files from Windows Explorer."
        )
        return ProjectFileImportBatchResult(
            results=[
                ProjectFileImportResult(
                    source_path=item.path,
                    success=False,
                    message=message,
                )
                for item in args.files
            ],
            rejected=list(args.rejected),
        )

    def build_flush_failure_result(
        self, args: ProjectFileArgs, target: ProjectImportTarget
    ) -> ProjectFileImportBatchResult:
        message = "Pending database changes could not be saved before import."
        return ProjectFileImportBatchResult(
            results=[
                ProjectFileImportResult(
                    source_path=item.path,
                    success=False,
                    message=message,
                )
                for item in args.files
            ],
            rejected=list(args.rejected),
            target_db_path=target.file_path,
            selected_project_uid=target.project_uid,
            import_as_orphaned_due_to_deleted_target=(
                target.import_as_orphaned_due_to_deleted_target
            ),
        )

    def execute_imports(
        self,
        args: ProjectFileArgs,
        target: ProjectImportTarget,
        refresh_after_import: bool = True,
    ) -> ProjectFileImportBatchResult:
        before_uids = self._project_uids_for_file(target.file_path)
        results = [self._import_file(item, target) for item in args.files]
        success_count = sum(1 for result in results if result.success)
        selected_project_uid = target.project_uid
        batch = ProjectFileImportBatchResult(
            results=results,
            rejected=list(args.rejected),
            target_db_path=target.file_path,
            selected_project_uid=selected_project_uid,
            import_as_orphaned_due_to_deleted_target=(
                target.import_as_orphaned_due_to_deleted_target
            ),
            refresh_pending=bool(success_count),
            project_uids_before=frozenset(before_uids),
        )
        if refresh_after_import and success_count:
            return self.refresh_import_result(batch)
        return batch

    def refresh_import_result(
        self, result: ProjectFileImportBatchResult
    ) -> ProjectFileImportBatchResult:
        if not result.refresh_pending:
            return result
        if not result.target_db_path:
            return replace(result, refresh_pending=False)
        success_count = result.succeeded
        selected_project_uid = result.selected_project_uid
        if success_count:
            if not self._import_service.reload_and_notify(result.target_db_path):
                return replace(
                    result,
                    results=self._mark_successes_refresh_failed(result.results),
                    refresh_pending=False,
                )
            if not result.import_as_orphaned_due_to_deleted_target:
                selected_project_uid = (
                    selected_project_uid
                    or self._detect_new_project_uid(
                        result.target_db_path, result.project_uids_before
                    )
                )
            if success_count == 1:
                results = self._with_single_success_project_name(
                    result.results, result.target_db_path, selected_project_uid
                )
            else:
                results = result.results
        else:
            results = result.results
        return replace(
            result,
            results=results,
            selected_project_uid=selected_project_uid,
            refresh_pending=False,
        )

    def _import_file(
        self, item: ParsedProjectFileArg, target: ProjectImportTarget
    ) -> ProjectFileImportResult:
        if not Path(item.path).is_file():
            return ProjectFileImportResult(
                source_path=item.path,
                success=False,
                message="File does not exist.",
            )
        try:
            if item.extension == PROJECT_IMPORT_EXTENSION_OST:
                success = self._import_service.import_ost(
                    item.path,
                    target.file_path,
                    target.project_uid,
                    refresh=False,
                )
            else:
                success = self._import_service.import_osp(
                    item.path,
                    target.file_path,
                    target.project_uid,
                    refresh=False,
                )
        except Exception as exc:
            self._logger.exception("Project file import failed for %s", item.path)
            return ProjectFileImportResult(
                source_path=item.path,
                success=False,
                message=str(exc) or "Import failed.",
            )
        if not success:
            return ProjectFileImportResult(
                source_path=item.path,
                success=False,
                message="The file could not be imported.",
            )
        return ProjectFileImportResult(
            source_path=item.path,
            success=True,
            message="Imported successfully.",
            project_name=Path(item.path).stem,
        )

    def _mark_successes_refresh_failed(
        self, results: List[ProjectFileImportResult]
    ) -> List[ProjectFileImportResult]:
        return [
            (
                replace(
                    result,
                    success=False,
                    message=(
                        "Imported, but the database could not be refreshed. Reopen the "
                        "database to see the imported project."
                    ),
                )
                if result.success
                else result
            )
            for result in results
        ]

    def _with_single_success_project_name(
        self,
        results: List[ProjectFileImportResult],
        file_path: str,
        project_uid: Optional[str],
    ) -> List[ProjectFileImportResult]:
        project_name = self._project_name(file_path, project_uid)
        updated: List[ProjectFileImportResult] = []
        for result in results:
            if result.success and project_name:
                updated.append(replace(result, project_name=project_name))
            else:
                updated.append(result)
        return updated

    def resolve_target(
        self, current_target: Optional[ProjectImportCurrentTarget]
    ) -> Optional[ProjectImportTarget]:
        enabled_paths = self._enabled_existing_paths()
        if not enabled_paths:
            return None
        if current_target and current_target.file_path:
            target = self._target_if_enabled(
                current_target.file_path,
                enabled_paths,
                current_target.project_uid,
            )
            if target:
                return target
        workspace_target = self._workspace_target(enabled_paths)
        if workspace_target:
            return workspace_target
        first_path = next(iter(enabled_paths.values()))
        return ProjectImportTarget(file_path=first_path)

    def _enabled_existing_paths(self) -> dict[str, str]:
        paths: dict[str, str] = {}
        for entry in self._file_state_model.file_entries:
            if not entry.is_checked:
                continue
            locator = entry.runtime_locator
            if entry.backend == DatabaseBackend.SQL_SERVER:
                paths[normalize_path(locator)] = locator
            elif Path(locator).is_file():
                paths[normalize_path(locator)] = locator
        return paths

    def _target_if_enabled(
        self,
        file_path: str,
        enabled_paths: dict[str, str],
        project_uid: Optional[str] = None,
    ) -> Optional[ProjectImportTarget]:
        resolved = enabled_paths.get(normalize_path(file_path))
        if not resolved:
            return None
        if is_deleted_bids_project_uid(project_uid):
            return ProjectImportTarget(
                file_path=resolved,
                project_uid=None,
                import_as_orphaned_due_to_deleted_target=True,
            )
        return ProjectImportTarget(file_path=resolved, project_uid=project_uid)

    def _workspace_target(
        self, enabled_paths: dict[str, str]
    ) -> Optional[ProjectImportTarget]:
        selected = self._workspace_state_model.state.project_workspace.selected_node
        if selected is None:
            return None
        project_uid = (
            selected.project_uid
            if selected.kind == WORKSPACE_NODE_KIND_PROJECT
            else None
        )
        if selected.kind == WORKSPACE_NODE_KIND_BID and selected.bid_uid:
            project_uid = self._project_uid_for_bid(
                selected.file_path, selected.bid_uid
            )
        return self._target_if_enabled(selected.file_path, enabled_paths, project_uid)

    def _project_uid_for_bid(self, file_path: str, bid_uid: str) -> Optional[str]:
        target_norm = normalize_path(file_path)
        hierarchy = self._project_data.get_hierarchy()
        for file_entry in hierarchy.loaded_files:
            if normalize_path(file_entry.file_path) != target_norm:
                continue
            for project_uid, project_info in file_entry.bid_projects.items():
                if any(bid.uid == bid_uid for bid in project_info.bids):
                    return project_uid
        return None

    def _project_uids_for_file(self, file_path: str) -> set[str]:
        target_norm = normalize_path(file_path)
        hierarchy = self._project_data.get_hierarchy()
        for file_entry in hierarchy.loaded_files:
            if normalize_path(file_entry.file_path) == target_norm:
                return set(file_entry.bid_projects.keys())
        return set()

    def _detect_new_project_uid(
        self, file_path: str, before_uids: Iterable[str]
    ) -> Optional[str]:
        before = {str(uid) for uid in before_uids}
        after = self._project_uids_for_file(file_path)
        new_uids = sorted(after - before)
        if len(new_uids) == 1:
            return new_uids[0]
        return None

    def _project_name(
        self, file_path: str, project_uid: Optional[str]
    ) -> Optional[str]:
        if not project_uid:
            return None
        target_norm = normalize_path(file_path)
        hierarchy = self._project_data.get_hierarchy()
        for file_entry in hierarchy.loaded_files:
            if normalize_path(file_entry.file_path) != target_norm:
                continue
            project = file_entry.bid_projects.get(project_uid)
            if project is not None:
                return project.name
        return None
