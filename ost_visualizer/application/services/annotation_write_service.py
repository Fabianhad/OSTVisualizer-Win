from typing import List, Optional, Tuple
from ..dtos.insert_annotation_spec_dto import InsertAnnotationSpec
from ..dtos.paste_ref_remap_dto import PasteRefRemap
from ..use_cases.project.delete_annotations_use_case import DeleteAnnotationsUseCase
from ..use_cases.project.insert_annotations_use_case import InsertAnnotationsUseCase
from ..use_cases.project.save_annotation_positions_use_case import (
    SaveAnnotationPositionsUseCase,
)
from ..use_cases.project.save_annotation_text_properties_use_case import (
    SaveAnnotationTextPropertiesUseCase,
)
from ..use_cases.project.save_annotation_styles_use_case import (
    SaveAnnotationStylesUseCase,
)
from .active_bid_write_guard import ActiveBidWriteGuard
from .base_write_service import BaseWriteService


class AnnotationWriteService(BaseWriteService):
    def __init__(
        self,
        save_annotation_positions: SaveAnnotationPositionsUseCase,
        save_annotation_text_properties: SaveAnnotationTextPropertiesUseCase,
        save_annotation_styles: SaveAnnotationStylesUseCase,
        insert_annotations: InsertAnnotationsUseCase,
        delete_annotations: DeleteAnnotationsUseCase,
        reload_database=None,
        event_bus=None,
        logger=None,
        bid_write_guard: Optional[ActiveBidWriteGuard] = None,
    ) -> None:
        if bid_write_guard is None:
            raise ValueError("AnnotationWriteService requires bid_write_guard")
        super().__init__(reload_database, event_bus, logger)
        self._bid_write_guard = bid_write_guard
        self._save_annotation_positions = save_annotation_positions
        self._save_annotation_text_properties = save_annotation_text_properties
        self._save_annotation_styles = save_annotation_styles
        self._insert_annotations = insert_annotations
        self._delete_annotations = delete_annotations

    def save_annotation_positions(
        self,
        db_path: str,
        positions: List[Tuple[str, str, List[float]]],
        publish_database_refreshed_after_write: bool = True,
    ) -> bool:
        if self._bid_write_guard.blocks_active_locked_bid_write(db_path):
            return False
        success = self._save_annotation_positions.execute(db_path, positions)
        if success and publish_database_refreshed_after_write:
            self.reload_and_notify(db_path)
        return success

    def save_annotation_text_properties(
        self,
        db_path: str,
        updates: List[Tuple[str, str, dict]],
        publish_database_refreshed_after_write: bool = True,
    ) -> bool:
        if self._bid_write_guard.blocks_active_locked_bid_write(db_path):
            return False
        success = self._save_annotation_text_properties.execute(db_path, updates)
        if success and publish_database_refreshed_after_write:
            self.reload_and_notify(db_path)
        return success

    def save_annotation_styles(
        self,
        db_path: str,
        updates: List[Tuple[str, str, dict]],
        publish_database_refreshed_after_write: bool = True,
    ) -> bool:
        if self._bid_write_guard.blocks_active_locked_bid_write(db_path):
            return False
        success = self._save_annotation_styles.execute(db_path, updates)
        if success and publish_database_refreshed_after_write:
            self.reload_and_notify(db_path)
        return success

    def save_annotation_text_properties_and_positions(
        self,
        db_path: str,
        updates: List[Tuple[str, str, dict]],
        positions: List[Tuple[str, str, List[float]]],
        publish_database_refreshed_after_write: bool = True,
    ) -> bool:
        if self._bid_write_guard.blocks_active_locked_bid_write(db_path):
            return False
        success = True
        if updates:
            success = self._save_annotation_text_properties.execute(db_path, updates)
        if success and positions:
            success = self._save_annotation_positions.execute(db_path, positions)
        if success and publish_database_refreshed_after_write:
            self.reload_and_notify(db_path)
        return success

    def insert_annotations(
        self,
        db_path: str,
        bid_uid: str,
        specs: List[InsertAnnotationSpec],
        ref_remap: Optional[PasteRefRemap] = None,
        publish_database_refreshed_after_write: bool = True,
    ) -> List[str]:
        if self._bid_write_guard.blocks_active_locked_bid_write(db_path, bid_uid):
            return []
        new_uids = self._insert_annotations.execute(
            db_path, bid_uid, specs, ref_remap=ref_remap
        )
        if new_uids and publish_database_refreshed_after_write:
            self.reload_and_notify(db_path)
        return new_uids

    def delete_annotations(
        self,
        db_path: str,
        annotations: List[Tuple[str, str]],
        publish_database_refreshed_after_write: bool = True,
    ) -> bool:
        if self._bid_write_guard.blocks_active_locked_bid_write(db_path):
            return False
        success = self._delete_annotations.execute(db_path, annotations)
        if success and publish_database_refreshed_after_write:
            self.reload_and_notify(db_path)
        return success
