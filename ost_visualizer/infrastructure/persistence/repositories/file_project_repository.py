import logging
import os
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional
import pyodbc
from ....application.interfaces.i_database_descriptor_registry import (
    IDatabaseDescriptorRegistry,
)
from ....domain.dtos.raw_bid_data_dto import RawBidData
from ....domain.entities.cdn_type import CdnType
from ....domain.entities.file_results import BidLoadResult, FileLoadResult
from ....domain.entities.hierarchy import Hierarchy
from ....domain.entities.hierarchy_data import HierarchyData, HierarchyFileEntry
from ....domain.entities.page import Page, build_pages_from_bid_data
from ....domain.repositories.i_file_parser import IFileParser
from ....domain.repositories.i_project_repository import IProjectRepository
from ...mdb.mdb_reader import MdbReader
from ...mdb.schema_compatibility import UnsupportedMdbSchemaError
from ...parsers.position_parser import clear_caches as _clear_position_caches


@dataclass
class _LoadedFileCache:
    file_path: str
    created_at: float
    parsed_hierarchy: HierarchyFileEntry
    cdn_types: Dict[str, CdnType] = field(default_factory=dict)
    pages: Dict[str, Page] = field(default_factory=dict)


class MdbFileParser(IFileParser):
    def __init__(
        self,
        logger: Optional[logging.Logger] = None,
        parser: Optional[MdbReader] = None,
    ) -> None:
        self.logger = logger or logging.getLogger(__name__)
        self.parser: MdbReader = parser or MdbReader(logger=self.logger)

    def close_connection(self, file_path: Optional[str] = None) -> None:
        self.parser.close_connection(file_path)

    def refresh_connection(self, file_path: str) -> None:
        self.parser.refresh_connection(file_path)

    def parse(self, file_path: str) -> FileLoadResult:
        parsed_hierarchy, cdn_types = self.parser.parse_file(file_path)
        return FileLoadResult(
            success=True,
            parsed_hierarchy=parsed_hierarchy,
            cdn_types=cdn_types,
        )

    def load_bid_data(self, file_path: str, bid_uid: str) -> BidLoadResult:
        (
            bid_conditions,
            bid_takeoffs,
            bid_areas,
            bid_pages,
            page_area_selections,
            cdn_types,
            bid_annotations,
            bid_condition_folders,
            selected_page_uid,
            takeoff_extras,
            cover_sheet_data,
            page_delete_content_uids,
        ) = self.parser.get_bid_data(file_path, bid_uid)
        pages = build_pages_from_bid_data(bid_pages, bid_takeoffs)
        bid_layers = self._load_bid_layers(file_path, bid_uid)
        return BidLoadResult(
            bid_conditions=bid_conditions,
            bid_takeoffs=bid_takeoffs,
            bid_areas=bid_areas,
            bid_pages=bid_pages,
            pages=pages,
            page_area_selections=page_area_selections,
            bid_annotations=bid_annotations,
            bid_layers=bid_layers,
            bid_condition_folders=bid_condition_folders,
            selected_page_uid=selected_page_uid,
            takeoff_extras=takeoff_extras,
            cover_sheet_data=cover_sheet_data,
            page_delete_content_uids=page_delete_content_uids,
        )

    def get_bid_layers_for_sidebar(self, file_path: str, bid_uid: str):
        return self.parser.get_bid_layers_for_sidebar(file_path, bid_uid)

    def _load_bid_layers(self, file_path: str, bid_uid: str):
        try:
            return self.parser.get_bid_layers_for_sidebar(file_path, bid_uid)
        except (pyodbc.Error, TypeError, ValueError) as exc:
            self.logger.warning(
                "Failed to load bid layers for %s in %s: %s",
                bid_uid,
                file_path,
                exc,
            )
            return []

    def get_database_statistics(self, file_path: str) -> Dict[str, int]:
        return self.parser.get_database_statistics(file_path)

    def get_raw_bid_data(self, file_path: str, bid_uid: str) -> RawBidData:
        return self.parser.get_raw_bid_data(file_path, bid_uid)


class FileProjectRepository(IProjectRepository):
    def __init__(
        self,
        parser: IFileParser,
        logger: Optional[logging.Logger] = None,
        descriptor_registry: Optional[IDatabaseDescriptorRegistry] = None,
    ):
        self.parser = parser
        self.logger = logger or logging.getLogger(__name__)
        self._descriptor_registry = descriptor_registry
        self._active_file_path: Optional[str] = None
        self._current_hierarchy = Hierarchy()
        self._loaded_files: Dict[str, _LoadedFileCache] = {}
        self._state_lock = threading.RLock()

    @property
    def active_file_path(self) -> Optional[str]:
        with self._state_lock:
            return self._active_file_path

    @property
    def current_hierarchy_data(self) -> HierarchyData:
        with self._state_lock:
            return self._current_hierarchy.data

    def get_cdn_types(self, file_path: Optional[str] = None) -> Dict[str, CdnType]:
        with self._state_lock:
            target_path = file_path or self._active_file_path
            cache = self._loaded_files.get(target_path) if target_path else None
            return dict(cache.cdn_types) if cache is not None else {}

    def register_loaded_hierarchy(
        self,
        file_entry: HierarchyFileEntry,
        cdn_types: Dict[str, CdnType],
    ) -> HierarchyData:
        with self._state_lock:
            file_path = file_entry.file_path
            cached = self._loaded_files.get(file_path)
            if cached is None:
                self._loaded_files[file_path] = _LoadedFileCache(
                    file_path=file_path,
                    created_at=file_entry.created_at or time.time(),
                    parsed_hierarchy=file_entry,
                    cdn_types=dict(cdn_types),
                )
            else:
                cached.parsed_hierarchy = file_entry
                cached.cdn_types = dict(cdn_types)
            if self._active_file_path is None:
                self._active_file_path = file_path
            self._rebuild_merged_hierarchy()
            return self._current_hierarchy.data

    def load_file(self, file_path: str) -> FileLoadResult:
        with self._state_lock:
            cache = self._loaded_files.get(file_path)
            if cache is not None:
                self._active_file_path = file_path
                return FileLoadResult(
                    success=True,
                    hierarchy=self._current_hierarchy.data,
                    cdn_types=dict(cache.cdn_types),
                    pages=dict(cache.pages),
                )
        try:
            result = self.parser.parse(file_path)
        except UnsupportedMdbSchemaError as exc:
            error_message = (
                f"{exc} If this is an older OST database, test only on a backup copy."
            )
            self.logger.error("Unsupported MDB schema for %s: %s", file_path, exc)
            return FileLoadResult(success=False, error_message=error_message)
        except Exception as exc:
            error_message = str(exc) or exc.__class__.__name__
            self.logger.exception("Load failed for %s: %s", file_path, error_message)
            return FileLoadResult(success=False, error_message=error_message)
        if result.success:
            with self._state_lock:
                existing = self._loaded_files.get(file_path)
                if existing is not None:
                    self._active_file_path = file_path
                    result.hierarchy = self._current_hierarchy.data
                    result.cdn_types = dict(existing.cdn_types)
                    result.pages = dict(existing.pages)
                    return result
                created_at = (
                    os.path.getctime(file_path)
                    if Path(file_path).suffix.casefold() == ".mdb"
                    and os.path.exists(file_path)
                    else time.time()
                )
                self._loaded_files[file_path] = _LoadedFileCache(
                    file_path=file_path,
                    created_at=created_at,
                    parsed_hierarchy=result.parsed_hierarchy,
                    cdn_types=result.cdn_types,
                    pages=result.pages,
                )
                self._active_file_path = file_path
                self._rebuild_merged_hierarchy()
                result.hierarchy = self._current_hierarchy.data
        return result

    def _rebuild_merged_hierarchy(self) -> None:
        sorted_caches = sorted(
            self._loaded_files.values(),
            key=lambda c: (c.created_at, os.path.normcase(c.file_path)),
        )
        file_entries: List[HierarchyFileEntry] = []
        for cache in sorted_caches:
            entry = cache.parsed_hierarchy
            entry.file_path = cache.file_path
            entry.created_at = cache.created_at
            if not entry.display_name:
                descriptor = (
                    self._descriptor_registry.resolve(cache.file_path)
                    if self._descriptor_registry is not None
                    else None
                )
                entry.display_name = (
                    descriptor.display_name
                    if descriptor is not None
                    else entry.database_name or os.path.basename(cache.file_path)
                )
            file_entries.append(entry)
        self._current_hierarchy.set(HierarchyData(loaded_files=file_entries))

    def unload_file(self, file_path: Optional[str] = None) -> bool:
        with self._state_lock:
            target_path = file_path or self._active_file_path
            if not target_path or target_path not in self._loaded_files:
                return False
            _clear_position_caches()
            self.parser.close_connection(target_path)
            del self._loaded_files[target_path]
            if target_path == self._active_file_path:
                if self._loaded_files:
                    self._active_file_path = next(iter(self._loaded_files.keys()))
                else:
                    self._active_file_path = None
            if self._loaded_files:
                self._rebuild_merged_hierarchy()
            else:
                self._current_hierarchy = Hierarchy()
            return True

    def load_bid(self, bid_uid: str, file_path: Optional[str] = None) -> BidLoadResult:
        if not file_path:
            self.logger.error(
                "file_path is required for load_bid (bid_uid=%s)", bid_uid
            )
            return BidLoadResult()
        result = self.prepare_bid_load(bid_uid, file_path)
        self.apply_bid_load(file_path)
        return result

    def prepare_bid_load(self, bid_uid: str, file_path: str) -> BidLoadResult:
        with self._state_lock:
            loaded = file_path in self._loaded_files
        if not loaded:
            self.logger.warning("File not loaded: %s (bid_uid=%s)", file_path, bid_uid)
            return BidLoadResult()
        return self.parser.load_bid_data(file_path, bid_uid)

    def apply_bid_load(self, file_path: str) -> None:
        with self._state_lock:
            if file_path not in self._loaded_files:
                raise RuntimeError(
                    "The navigation database was unloaded while reading."
                )
            self._active_file_path = file_path

    def reload_database(self, file_path: Optional[str] = None) -> FileLoadResult:
        if not file_path:
            error_message = "file_path is required for reload_database"
            self.logger.error(error_message)
            return FileLoadResult(success=False, error_message=error_message)
        with self._state_lock:
            loaded = file_path in self._loaded_files
        if not loaded:
            error_message = f"File not found in loaded files: {file_path}"
            self.logger.error(error_message)
            return FileLoadResult(success=False, error_message=error_message)
        try:
            self.parser.refresh_connection(file_path)
            _clear_position_caches()
            result = self.parser.parse(file_path)
        except Exception as exc:
            error_message = f"Failed to refresh database file: {exc}"
            self.logger.exception("Error refreshing database %s: %s", file_path, exc)
            return FileLoadResult(success=False, error_message=error_message)
        if result.success:
            with self._state_lock:
                if file_path not in self._loaded_files:
                    return FileLoadResult(
                        success=False,
                        error_message=(
                            "The navigation database was unloaded while refreshing."
                        ),
                    )
                cache = self._loaded_files[file_path]
                cache.parsed_hierarchy = result.parsed_hierarchy
                cache.cdn_types = dict(result.cdn_types)
                self._rebuild_merged_hierarchy()
                result.hierarchy = self._current_hierarchy.data
        return result
