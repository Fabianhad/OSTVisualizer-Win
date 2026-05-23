from typing import List, Optional, Tuple
from ..dtos.insert_annotation_spec_dto import InsertAnnotationSpec
from ..dtos.paste_ref_remap_dto import PasteRefRemap
from ..use_cases.project.delete_annotations_use_case import DeleteAnnotationsUseCase
from ..use_cases.project.insert_annotations_use_case import InsertAnnotationsUseCase
from ..use_cases.project.save_annotation_positions_use_case import (
    SaveAnnotationPositionsUseCase,
)
from .active_bid_write_guard import ActiveBidWriteGuard
from .base_write_service import BaseWriteService


class AnnotationWriteService(BaseWriteService):
    def __init__(
        self,
        save_annotation_positions: SaveAnnotationPositionsUseCase,
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
        self._insert_annotations = insert_annotations
        self._delete_annotations = delete_annotations

    def save_annotation_positions(
        self, db_path: str, positions: List[Tuple[str, str, List[float]]]
    ) -> bool:
        if self._bid_write_guard.blocks_active_locked_bid_write(
            "save_annotation_positions", db_path
        ):
            return False
        success = self._save_annotation_positions.execute(db_path, positions)
        if success:
            self.reload_and_notify(db_path)
        return success

    def insert_annotations(
        self,
        db_path: str,
        bid_uid: str,
        specs: List[InsertAnnotationSpec],
        ref_remap: Optional[PasteRefRemap] = None,
    ) -> List[str]:
        if self._bid_write_guard.blocks_active_locked_bid_write(
            "insert_annotations", db_path, bid_uid
        ):
            return []
        new_uids = self._insert_annotations.execute(
            db_path, bid_uid, specs, ref_remap=ref_remap
        )
        if new_uids:
            self.reload_and_notify(db_path)
        return new_uids

    def delete_annotations(
        self, db_path: str, annotations: List[Tuple[str, str]]
    ) -> bool:
        if self._bid_write_guard.blocks_active_locked_bid_write(
            "delete_annotations", db_path
        ):
            return False
        success = self._delete_annotations.execute(db_path, annotations)
        if success:
            self.reload_and_notify(db_path)
        return success
