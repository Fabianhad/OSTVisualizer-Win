import hashlib
import json
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Optional
from ..application.services.mcp_read_service import McpDatabaseRef
from ..domain.entities.workspace_state import (
    WORKSPACE_ACTIVE_VIEW_3D,
    WORKSPACE_KEY_ACTIVE_VIEW,
    WORKSPACE_KEY_BID_UID,
    WORKSPACE_KEY_FILE_PATH,
    WORKSPACE_KEY_KIND,
    WORKSPACE_KEY_PROJECT_UID,
    WORKSPACE_KEY_PROJECT_WORKSPACE,
    WORKSPACE_KEY_SELECTED_NODE,
    WORKSPACE_KEY_TAKEOFF_WORKSPACE,
    WORKSPACE_VALID_ACTIVE_VIEWS,
)
from ..infrastructure.app_paths import get_app_data_dir
from .output_artifacts import MCP_OUTPUT_DIR_NAME


@dataclass
class McpWorkspaceSelection:
    selected_node_kind: Optional[str] = None
    file_path: Optional[str] = None
    database_id: Optional[str] = None
    project_uid: Optional[str] = None
    bid_uid: Optional[str] = None
    active_view: str = WORKSPACE_ACTIVE_VIEW_3D


class DatabaseRegistry:
    def __init__(
        self,
        app_data_dir: Optional[Path] = None,
        logger: Optional[logging.Logger] = None,
    ):
        self._app_data_dir = Path(app_data_dir) if app_data_dir else get_app_data_dir()
        self._logger = logger or logging.getLogger(__name__)
        self._databases: List[McpDatabaseRef] = []
        self._selection = McpWorkspaceSelection()
        self.reload()

    @property
    def databases(self) -> List[McpDatabaseRef]:
        return list(self._databases)

    @property
    def output_artifacts_dir(self) -> Path:
        return self._app_data_dir / MCP_OUTPUT_DIR_NAME

    @property
    def workspace_selection(self) -> McpWorkspaceSelection:
        selection = self._selection
        return McpWorkspaceSelection(
            selected_node_kind=selection.selected_node_kind,
            file_path=selection.file_path,
            database_id=selection.database_id,
            project_uid=selection.project_uid,
            bid_uid=selection.bid_uid,
            active_view=selection.active_view,
        )

    def reload(self) -> None:
        self._databases = self._build_database_refs(self._read_file_state_paths())
        self._selection = self._read_workspace_selection()

    def get_database_id_for_path(self, file_path: str) -> Optional[str]:
        target = self._normalize(file_path)
        for db in self._databases:
            if self._normalize(db.file_path) == target:
                return db.database_id
        return None

    def _read_file_state_paths(self) -> List[str]:
        payload = self._read_json(self._app_data_dir / "file_state.json")
        entries = payload.get("file_entries") if isinstance(payload, dict) else None
        if not isinstance(entries, list):
            return []
        paths = []
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            if not bool(entry.get("is_checked", True)):
                continue
            file_path = entry.get("file_path")
            if file_path:
                paths.append(str(file_path))
        return paths

    def _read_workspace_selection(self) -> McpWorkspaceSelection:
        payload = self._read_json(self._app_data_dir / "workspace_state.json")
        if not isinstance(payload, dict):
            return McpWorkspaceSelection()
        takeoff = payload.get(WORKSPACE_KEY_TAKEOFF_WORKSPACE, {})
        project = payload.get(WORKSPACE_KEY_PROJECT_WORKSPACE, {})
        selected = (
            project.get(WORKSPACE_KEY_SELECTED_NODE, {})
            if isinstance(project, dict)
            else {}
        )
        if not isinstance(selected, dict):
            selected = {}
        file_path = selected.get(WORKSPACE_KEY_FILE_PATH)
        database_id = (
            self.get_database_id_for_path(str(file_path)) if file_path else None
        )
        active_view = str(
            takeoff.get(WORKSPACE_KEY_ACTIVE_VIEW, WORKSPACE_ACTIVE_VIEW_3D)
        ).lower()
        if active_view not in WORKSPACE_VALID_ACTIVE_VIEWS:
            active_view = WORKSPACE_ACTIVE_VIEW_3D
        return McpWorkspaceSelection(
            selected_node_kind=selected.get(WORKSPACE_KEY_KIND),
            file_path=str(file_path) if file_path else None,
            database_id=database_id,
            project_uid=selected.get(WORKSPACE_KEY_PROJECT_UID) or None,
            bid_uid=selected.get(WORKSPACE_KEY_BID_UID) or None,
            active_view=active_view,
        )

    def _build_database_refs(self, file_paths: Iterable[str]) -> List[McpDatabaseRef]:
        seen = set()
        refs = []
        for raw_path in file_paths:
            path = self._validated_database_path(raw_path)
            if path is None:
                continue
            norm = self._normalize(str(path))
            if norm in seen:
                continue
            seen.add(norm)
            refs.append(
                McpDatabaseRef(
                    database_id=self._database_id(norm),
                    file_path=str(path),
                    display_name=path.stem,
                )
            )
        return refs

    def _validated_database_path(self, raw_path: str) -> Optional[Path]:
        try:
            path = Path(raw_path).expanduser().resolve()
        except (OSError, RuntimeError):
            self._logger.warning("Ignoring invalid configured database path")
            return None
        if path.suffix.lower() != ".mdb":
            self._logger.warning(
                "Ignoring configured database path with non-MDB suffix"
            )
            return None
        if not path.exists() or not path.is_file():
            self._logger.warning("Ignoring configured database path that is missing")
            return None
        return path

    @staticmethod
    def _database_id(normalized_path: str) -> str:
        return hashlib.sha256(normalized_path.encode("utf-8")).hexdigest()[:16]

    @staticmethod
    def _normalize(file_path: str) -> str:
        return os.path.normcase(os.path.abspath(os.path.normpath(file_path)))

    @staticmethod
    def _read_json(path: Path) -> dict:
        try:
            with path.open("r", encoding="utf-8") as handle:
                payload = json.load(handle)
            return payload if isinstance(payload, dict) else {}
        except FileNotFoundError:
            return {}
        except (OSError, json.JSONDecodeError):
            return {}
