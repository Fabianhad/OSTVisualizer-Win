from typing import List, Optional
from ...application.dtos.annotation_creation_factory import AnnotationCreationFactory
from ...application.dtos.insert_annotation_spec_dto import InsertAnnotationSpec
from ...application.dtos.paste_ref_remap_dto import PasteRefRemap
from ...application.events.app_events import AppEvents
from ...domain.entities.annotation import (
    ANNOTATION_TYPE_NAMED_VIEW,
    BidAnnotation,
)
from ...domain.entities.identity_refs import BidRef
from ...domain.entities.named_view import normalize_named_view_position


class AnnotationWriteCoordinator:
    def __init__(self, annotation_write_service, project_data_service, event_bus):
        self._write_svc = annotation_write_service
        self._data_svc = project_data_service
        self._event_bus = event_bus

    def save_positions(self, db_path: str, positions: List[tuple]) -> bool:
        if not positions:
            return True
        if not self._write_svc.save_annotation_positions(
            db_path, positions, publish_database_refreshed_after_write=False
        ):
            return False
        page_uids = self._data_svc.update_annotation_positions(positions)
        self.publish_annotations_changed_for_pages(
            page_uids,
            self._annotation_uids_from_changes(positions),
            self._annotation_types_from_changes(positions),
        )
        return True

    def save_text_properties(self, db_path: str, updates: List[tuple]) -> bool:
        if not updates:
            return True
        if not self._write_svc.save_annotation_text_properties(
            db_path, updates, publish_database_refreshed_after_write=False
        ):
            return False
        page_uids = self._data_svc.update_annotation_text_properties(updates)
        self.publish_annotations_changed_for_pages(
            page_uids,
            self._annotation_uids_from_changes(updates),
            self._annotation_types_from_changes(updates),
        )
        return True

    def save_styles(self, db_path: str, updates: List[tuple]) -> bool:
        if not updates:
            return True
        if not self._write_svc.save_annotation_styles(
            db_path, updates, publish_database_refreshed_after_write=False
        ):
            return False
        page_uids = self._data_svc.update_annotation_styles(updates)
        self.publish_annotations_changed_for_pages(
            page_uids,
            self._annotation_uids_from_changes(updates),
            self._annotation_types_from_changes(updates),
        )
        return True

    def save_text_and_positions(
        self, db_path: str, updates: List[tuple], positions: List[tuple]
    ) -> bool:
        if not updates and not positions:
            return True
        if not self._write_svc.save_annotation_text_properties_and_positions(
            db_path, updates, positions, publish_database_refreshed_after_write=False
        ):
            return False
        page_uids = []
        if updates:
            page_uids.extend(self._data_svc.update_annotation_text_properties(updates))
        if positions:
            page_uids.extend(self._data_svc.update_annotation_positions(positions))
        annotation_uids = self._annotation_uids_from_changes(updates)
        annotation_uids.extend(self._annotation_uids_from_changes(positions))
        annotation_types = self._annotation_types_from_changes(updates)
        annotation_types.extend(self._annotation_types_from_changes(positions))
        self.publish_annotations_changed_for_pages(
            page_uids, annotation_uids, annotation_types
        )
        return True

    def insert_annotations(
        self,
        bid_ref: BidRef,
        specs: List[InsertAnnotationSpec],
        ref_remap: Optional[PasteRefRemap] = None,
    ) -> List[str]:
        self.apply_default_annotation_layer(specs)
        new_uids = self._write_svc.insert_annotations(
            bid_ref.file_path,
            bid_ref.bid_uid,
            specs,
            ref_remap=ref_remap,
            publish_database_refreshed_after_write=False,
        )
        if not new_uids:
            return []
        inserted_specs = specs[: len(new_uids)]
        self._add_inserted_annotations_to_model(new_uids, inserted_specs)
        page_uids = self._annotation_page_uids_for_specs(inserted_specs)
        self.publish_annotations_changed_for_pages(
            page_uids, list(new_uids), self._annotation_types_from_specs(inserted_specs)
        )
        return list(new_uids)

    def delete_annotations(
        self, db_path: str, uids: List[str], specs: List[InsertAnnotationSpec]
    ) -> bool:
        if not uids:
            return True
        annotation_keys = [
            (uid, specs[i].annotation_type) for i, uid in enumerate(uids)
        ]
        if not self._write_svc.delete_annotations(
            db_path, annotation_keys, publish_database_refreshed_after_write=False
        ):
            return False
        page_uids = self._data_svc.remove_annotations_by_keys(annotation_keys)
        self.publish_annotations_changed_for_pages(
            page_uids, list(uids), self._annotation_types_from_specs(specs)
        )
        return True

    def delete_saved_annotations(
        self, db_path: str, saved_annotations: List[BidAnnotation]
    ) -> bool:
        if not saved_annotations:
            return True
        annotation_keys = [
            (annotation.uid, annotation.annotation_type)
            for annotation in saved_annotations
        ]
        if not self._write_svc.delete_annotations(
            db_path, annotation_keys, publish_database_refreshed_after_write=False
        ):
            return False
        annotation_uids = [annotation.uid for annotation in saved_annotations]
        annotation_types = [
            annotation.annotation_type for annotation in saved_annotations
        ]
        page_uids = self._data_svc.remove_annotations_by_keys(annotation_keys)
        self.publish_annotations_changed_for_pages(
            page_uids, annotation_uids, annotation_types
        )
        self.publish_named_view_deletes(saved_annotations)
        return True

    def insert_saved_annotations(
        self, bid_ref: BidRef, saved_annotations: List[BidAnnotation]
    ) -> List[BidAnnotation]:
        if not saved_annotations:
            return []
        restored_by_key = {}
        ref_remap = PasteRefRemap()
        named_views = [
            annotation for annotation in saved_annotations if annotation.is_namedview
        ]
        others = [
            annotation
            for annotation in saved_annotations
            if not annotation.is_namedview
        ]
        if named_views:
            specs = self.annotation_specs_from_saved(named_views)
            new_uids = self.insert_annotations(bid_ref, specs)
            for annotation, new_uid in zip(named_views, new_uids):
                ref_remap.namedview_uids[str(annotation.uid)] = str(new_uid)
                restored_by_key[(annotation.uid, annotation.annotation_type)] = (
                    self.annotation_with_uid(annotation, new_uid)
                )
        if others:
            specs = self.annotation_specs_from_saved(others)
            new_uids = self.insert_annotations(bid_ref, specs, ref_remap=ref_remap)
            for annotation, new_uid in zip(others, new_uids):
                restored_by_key[(annotation.uid, annotation.annotation_type)] = (
                    self.annotation_with_uid(annotation, new_uid)
                )
        return [
            restored_by_key[(annotation.uid, annotation.annotation_type)]
            for annotation in saved_annotations
            if (annotation.uid, annotation.annotation_type) in restored_by_key
        ]

    def publish_named_view_renames(self, updates: list) -> None:
        renames = [
            (str(uid), str(properties["Text"] or ""))
            for uid, ann_type, properties in updates
            if ann_type == ANNOTATION_TYPE_NAMED_VIEW and "Text" in properties
        ]
        if not renames:
            return
        self._data_svc.update_named_view_names(renames)
        for uid, name in renames:
            self._event_bus.publish(
                AppEvents.NAMED_VIEW_RENAMED,
                named_view_uid=uid,
                name=name,
            )

    def publish_named_view_deletes(self, annotations: List[BidAnnotation]) -> None:
        named_view_uids = [
            str(annotation.uid) for annotation in annotations if annotation.is_namedview
        ]
        if named_view_uids:
            self._event_bus.publish(
                AppEvents.NAMED_VIEW_DELETED,
                named_view_uids=named_view_uids,
            )

    def apply_default_annotation_layer(self, specs: List[InsertAnnotationSpec]) -> None:
        factory = AnnotationCreationFactory(self._data_svc.get_annotation_layer_uid())
        factory.assign_default_layer_to_specs(specs)

    def _add_inserted_annotations_to_model(
        self, new_uids: List[str], specs: List[InsertAnnotationSpec]
    ) -> None:
        annotations = []
        for uid, spec in zip(new_uids, specs):
            position = (
                normalize_named_view_position(spec.position)
                if spec.annotation_type == ANNOTATION_TYPE_NAMED_VIEW
                else list(spec.position)
            )
            annotations.append(
                BidAnnotation(
                    uid=str(uid),
                    annotation_type=str(spec.annotation_type),
                    page_uid=str(spec.page_uid),
                    layer_uid=str(spec.layer_uid or ""),
                    position=position,
                    color=str(spec.color),
                    width=float(spec.width or 0.0),
                    properties=dict(spec.properties),
                    visible=True,
                )
            )
        self._data_svc.add_annotations(annotations)

    @staticmethod
    def annotation_specs_from_saved(
        annotations: List[BidAnnotation],
    ) -> List[InsertAnnotationSpec]:
        return [
            InsertAnnotationSpec(
                page_uid=annotation.page_uid,
                annotation_type=annotation.annotation_type,
                position=list(annotation.position),
                color=annotation.color,
                width=annotation.width,
                properties=dict(annotation.properties),
                layer_uid=annotation.layer_uid,
            )
            for annotation in annotations
        ]

    @staticmethod
    def annotation_with_uid(annotation: BidAnnotation, uid: str) -> BidAnnotation:
        return BidAnnotation(
            uid=str(uid),
            annotation_type=annotation.annotation_type,
            page_uid=annotation.page_uid,
            layer_uid=annotation.layer_uid,
            position=list(annotation.position),
            color=annotation.color,
            width=annotation.width,
            properties=dict(annotation.properties),
            visible=annotation.visible,
        )

    @staticmethod
    def _annotation_page_uids_for_specs(
        specs: List[InsertAnnotationSpec],
    ) -> List[str]:
        return AnnotationWriteCoordinator._unique_ordered(
            str(spec.page_uid) for spec in specs
        )

    @staticmethod
    def _annotation_uids_from_changes(changes: List[tuple]) -> List[str]:
        return [str(uid) for uid, _annotation_type, _payload in changes]

    @staticmethod
    def _annotation_types_from_changes(changes: List[tuple]) -> List[str]:
        return [str(annotation_type) for _uid, annotation_type, _payload in changes]

    @staticmethod
    def _annotation_types_from_specs(
        specs: List[InsertAnnotationSpec],
    ) -> List[str]:
        return [str(spec.annotation_type) for spec in specs]

    @staticmethod
    def _unique_ordered(values) -> List[str]:
        result: List[str] = []
        seen = set()
        for value in values:
            if value and value not in seen:
                result.append(value)
                seen.add(value)
        return result

    def publish_annotations_changed_for_pages(
        self,
        page_uids: List[str],
        annotation_uids: List[str],
        annotation_types: List[str],
    ) -> None:
        event_types = [str(annotation_type) for annotation_type in annotation_types]
        seen = set()
        for page_uid in page_uids:
            if not page_uid or page_uid in seen:
                continue
            seen.add(page_uid)
            self._event_bus.publish(
                AppEvents.ANNOTATIONS_CHANGED,
                page_uid=page_uid,
                annotation_uids=list(annotation_uids),
                annotation_types=list(event_types),
            )
