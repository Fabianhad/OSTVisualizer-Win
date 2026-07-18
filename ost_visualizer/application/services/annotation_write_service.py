from typing import List, Optional, Tuple
from ..dtos.collaboration_dtos import (
    ChangeOperation,
    ResourceRef,
)
from ..dtos.insert_annotation_spec_dto import InsertAnnotationSpec
from ..dtos.paste_ref_remap_dto import PasteRefRemap
from ..interfaces.i_database_mutation_executor import IDatabaseMutationExecutor
from ..interfaces.i_database_session_registry import IDatabaseSessionRegistry
from ..use_cases.project.delete_annotations_use_case import DeleteAnnotationsUseCase
from ..use_cases.project.insert_annotations_use_case import InsertAnnotationsUseCase
from ..use_cases.project.save_annotation_positions_use_case import (
    SaveAnnotationPositionsUseCase,
)
from ..use_cases.project.save_annotation_styles_use_case import (
    SaveAnnotationStylesUseCase,
)
from ..use_cases.project.save_annotation_text_properties_use_case import (
    SaveAnnotationTextPropertiesUseCase,
)
from .active_bid_write_guard import ActiveBidWriteGuard
from .base_write_service import DatabaseMutationWriteService
from .database_concurrency_token_service import DatabaseConcurrencyTokenService


class AnnotationWriteService(DatabaseMutationWriteService):
    def __init__(
        self,
        save_annotation_positions: SaveAnnotationPositionsUseCase,
        save_annotation_text_properties: SaveAnnotationTextPropertiesUseCase,
        save_annotation_styles: SaveAnnotationStylesUseCase,
        insert_annotations: InsertAnnotationsUseCase,
        delete_annotations: DeleteAnnotationsUseCase,
        mutation_executor: IDatabaseMutationExecutor,
        session_registry: IDatabaseSessionRegistry,
        concurrency_tokens: DatabaseConcurrencyTokenService,
        reload_database=None,
        event_bus=None,
        logger=None,
        bid_write_guard: Optional[ActiveBidWriteGuard] = None,
        project_data_service=None,
    ) -> None:
        if bid_write_guard is None:
            raise ValueError("AnnotationWriteService requires bid_write_guard")
        if mutation_executor is None:
            raise ValueError("AnnotationWriteService requires mutation_executor")
        if session_registry is None:
            raise ValueError("AnnotationWriteService requires session_registry")
        if concurrency_tokens is None:
            raise ValueError("AnnotationWriteService requires concurrency_tokens")
        if project_data_service is None:
            raise ValueError("AnnotationWriteService requires project_data_service")
        super().__init__(
            reload_database=reload_database,
            event_bus=event_bus,
            mutation_executor=mutation_executor,
            session_registry=session_registry,
            concurrency_tokens=concurrency_tokens,
            logger=logger,
        )
        self._bid_write_guard = bid_write_guard
        self._save_annotation_positions = save_annotation_positions
        self._save_annotation_text_properties = save_annotation_text_properties
        self._save_annotation_styles = save_annotation_styles
        self._insert_annotations = insert_annotations
        self._delete_annotations = delete_annotations
        self._project_data = project_data_service

    def _bid_uid(self, db_path: str) -> Optional[int]:
        bid_ref = self._project_data.get_current_bid_ref()
        if bid_ref is None or bid_ref.file_path != db_path:
            return None
        return int(bid_ref.bid_uid)

    def _execute_mutation(self, db_path: str, resources, operation):
        resources = tuple(resources)
        result = self._execute_database_mutation(db_path, resources, operation)
        return result.value if result.success else None

    def _update_resources(self, db_path: str, annotations, operation) -> bool:
        resources = tuple(
            ResourceRef(
                "annotation",
                f"{annotation_type}/{uid}",
                self._bid_uid(db_path),
            )
            for uid, annotation_type, *_rest in annotations
        )
        if not resources:
            return False

        def execute(recorder):
            success = bool(operation())
            if success:
                for resource in resources:
                    recorder.record(resource, ChangeOperation.UPDATE)
            return success

        return bool(self._execute_mutation(db_path, resources, execute))

    def save_annotation_positions(
        self,
        db_path: str,
        positions: List[Tuple[str, str, List[float]]],
        publish_database_refreshed_after_write: bool = True,
    ) -> bool:
        if self._bid_write_guard.blocks_active_locked_bid_write(db_path):
            return False
        success = self._update_resources(
            db_path,
            positions,
            lambda: self._save_annotation_positions.execute(db_path, positions),
        )
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
        success = self._update_resources(
            db_path,
            updates,
            lambda: self._save_annotation_text_properties.execute(db_path, updates),
        )
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
        success = self._update_resources(
            db_path,
            updates,
            lambda: self._save_annotation_styles.execute(db_path, updates),
        )
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
        combined = list(updates) + list(positions)
        resources = tuple(
            ResourceRef(
                "annotation",
                f"{annotation_type}/{uid}",
                self._bid_uid(db_path),
            )
            for uid, annotation_type, _value in combined
        )

        def save_all(recorder):
            success = True
            if updates:
                success = self._save_annotation_text_properties.execute(
                    db_path, updates
                )
            if success and positions:
                success = self._save_annotation_positions.execute(db_path, positions)
            if success:
                for resource in resources:
                    recorder.record(resource, ChangeOperation.UPDATE)
            return success

        success = bool(self._execute_mutation(db_path, resources, save_all))
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
        collection = ResourceRef("annotations_collection", bid_uid, int(bid_uid))

        def insert(recorder):
            new_uids = self._insert_annotations.execute(
                db_path, bid_uid, specs, ref_remap=ref_remap
            )
            for spec, new_uid in zip(specs, new_uids):
                recorder.record(
                    ResourceRef(
                        "annotation",
                        f"{spec.annotation_type}/{new_uid}",
                        int(bid_uid),
                    ),
                    ChangeOperation.CREATE,
                )
            if new_uids:
                recorder.record(collection, ChangeOperation.UPDATE)
            return new_uids

        new_uids = self._execute_mutation(db_path, (collection,), insert) or []
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
        resources = tuple(
            ResourceRef(
                "annotation",
                f"{annotation_type}/{uid}",
                self._bid_uid(db_path),
            )
            for uid, annotation_type in annotations
        )

        def delete(recorder):
            success = self._delete_annotations.execute(db_path, annotations)
            if success:
                for resource in resources:
                    recorder.record(resource, ChangeOperation.DELETE)
            return success

        success = bool(self._execute_mutation(db_path, resources, delete))
        if success and publish_database_refreshed_after_write:
            self.reload_and_notify(db_path)
        return success
