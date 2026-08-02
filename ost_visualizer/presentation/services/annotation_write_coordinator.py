from dataclasses import dataclass
from typing import Callable, List, Optional
from ...application.dtos.annotation_creation_factory import AnnotationCreationFactory
from ...application.dtos.insert_annotation_spec_dto import InsertAnnotationSpec
from ...application.dtos.paste_ref_remap_dto import PasteRefRemap
from ...application.events.app_events import AppEvents
from ...domain.entities.annotation import (
    ANNOTATION_TYPE_HOTLINK,
    ANNOTATION_TYPE_NAMED_VIEW,
    BidAnnotation,
)
from ...domain.entities.identity_refs import BidRef
from ...domain.entities.named_view import normalize_named_view_position


@dataclass(frozen=True)
class InsertedAnnotationCopies:
    sources: tuple[BidAnnotation, ...]
    specs: tuple[InsertAnnotationSpec, ...]
    uids: tuple[str, ...]
    ref_remap: PasteRefRemap


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
        self._update_named_view_names(updates)
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
        new_uids = self._require_complete_identity_batch(new_uids, len(specs))
        inserted_specs = specs[: len(new_uids)]
        self._add_inserted_annotations_to_model(
            new_uids, inserted_specs, ref_remap=ref_remap
        )
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
        return True

    def insert_saved_annotations(
        self, bid_ref: BidRef, saved_annotations: List[BidAnnotation]
    ) -> List[BidAnnotation]:
        if not saved_annotations:
            return []
        result = self.insert_annotation_copies(
            bid_ref,
            saved_annotations,
            self.annotation_specs_from_saved(saved_annotations),
        )
        return [
            self.annotation_with_uid(
                annotation,
                uid,
                ref_remap=result.ref_remap,
            )
            for annotation, uid in zip(result.sources, result.uids)
        ]

    def insert_annotation_copies(
        self,
        bid_ref: BidRef,
        source_annotations: List[BidAnnotation],
        specs: List[InsertAnnotationSpec],
        *,
        ref_remap: Optional[PasteRefRemap] = None,
        insert_batch: Optional[
            Callable[
                [BidRef, List[InsertAnnotationSpec], Optional[PasteRefRemap]],
                List[str],
            ]
        ] = None,
    ) -> InsertedAnnotationCopies:
        if len(source_annotations) != len(specs):
            raise ValueError("Copied annotation sources and specs must stay aligned")
        remap = ref_remap or PasteRefRemap()
        insert = insert_batch or self.insert_annotations
        indexed_pairs = list(enumerate(zip(source_annotations, specs)))
        named_pairs = [
            (index, annotation, spec)
            for index, (annotation, spec) in indexed_pairs
            if annotation.is_namedview
        ]
        other_pairs = [
            (index, annotation, spec)
            for index, (annotation, spec) in indexed_pairs
            if not annotation.is_namedview
        ]
        inserted_by_index: dict[
            int, tuple[BidAnnotation, InsertAnnotationSpec, str]
        ] = {}
        if named_pairs:
            named_uids = self._require_complete_identity_batch(
                insert(
                    bid_ref,
                    [spec for _index, _annotation, spec in named_pairs],
                    remap,
                ),
                len(named_pairs),
            )
            for (index, annotation, spec), new_uid in zip(named_pairs, named_uids):
                remap.namedview_uids[str(annotation.uid)] = str(new_uid)
                inserted_by_index[index] = (annotation, spec, str(new_uid))
        source_named_view_uids = {
            str(annotation.uid)
            for annotation in source_annotations
            if annotation.is_namedview
        }
        external_named_view_targets = {
            str(annotation.properties.get("BidPageViewUID"))
            for _index, annotation, _spec in other_pairs
            if annotation.annotation_type == ANNOTATION_TYPE_HOTLINK
            and annotation.properties.get("BidPageViewUID")
            and str(annotation.properties["BidPageViewUID"])
            not in source_named_view_uids
        }
        existing_named_view_uids = (
            {
                str(annotation.uid)
                for annotation in self._data_svc.get_all_annotations()
                if annotation.is_namedview
                and str(annotation.uid) in external_named_view_targets
            }
            if external_named_view_targets
            else set()
        )
        insertable_others = [
            (index, annotation, spec)
            for index, annotation, spec in other_pairs
            if self._copy_reference_is_valid(
                annotation,
                source_named_view_uids,
                existing_named_view_uids,
                remap,
            )
        ]
        if insertable_others:
            other_uids = self._require_complete_identity_batch(
                insert(
                    bid_ref,
                    [spec for _index, _annotation, spec in insertable_others],
                    remap,
                ),
                len(insertable_others),
            )
            for (index, annotation, spec), new_uid in zip(
                insertable_others, other_uids
            ):
                inserted_by_index[index] = (annotation, spec, str(new_uid))
        inserted = [inserted_by_index[index] for index in sorted(inserted_by_index)]
        return InsertedAnnotationCopies(
            sources=tuple(annotation for annotation, _spec, _uid in inserted),
            specs=tuple(spec for _annotation, spec, _uid in inserted),
            uids=tuple(uid for _annotation, _spec, uid in inserted),
            ref_remap=remap,
        )

    @staticmethod
    def _require_complete_identity_batch(
        inserted_uids: List[str], expected_count: int
    ) -> List[str]:
        result = list(inserted_uids)
        if not result:
            return []
        if len(result) != expected_count:
            raise ValueError(
                "Annotation insert returned "
                f"{len(result)} identities for {expected_count} requested annotations"
            )
        return result

    def filter_copyable_annotations(
        self,
        source_annotations: List[BidAnnotation],
        specs: List[InsertAnnotationSpec],
    ) -> tuple[List[BidAnnotation], List[InsertAnnotationSpec]]:
        if len(source_annotations) != len(specs):
            raise ValueError("Copied annotation sources and specs must stay aligned")
        source_named_view_uids = {
            str(annotation.uid)
            for annotation in source_annotations
            if annotation.is_namedview
        }
        external_targets = {
            str(annotation.properties.get("BidPageViewUID") or "")
            for annotation in source_annotations
            if annotation.annotation_type == ANNOTATION_TYPE_HOTLINK
            and str(annotation.properties.get("BidPageViewUID") or "")
            not in source_named_view_uids
        }
        existing_named_view_uids = {
            str(annotation.uid)
            for annotation in self._data_svc.get_all_annotations()
            if annotation.is_namedview and str(annotation.uid) in external_targets
        }
        pairs = [
            (annotation, spec)
            for annotation, spec in zip(source_annotations, specs)
            if annotation.annotation_type != ANNOTATION_TYPE_HOTLINK
            or (
                str(annotation.properties.get("BidPageViewUID") or "")
                in source_named_view_uids.union(existing_named_view_uids)
            )
        ]
        return (
            [annotation for annotation, _spec in pairs],
            [spec for _annotation, spec in pairs],
        )

    @staticmethod
    def _copy_reference_is_valid(
        annotation: BidAnnotation,
        source_named_view_uids: set[str],
        existing_named_view_uids: set[str],
        ref_remap: PasteRefRemap,
    ) -> bool:
        if annotation.annotation_type != ANNOTATION_TYPE_HOTLINK:
            return True
        target_uid = str(annotation.properties.get("BidPageViewUID") or "")
        if not target_uid:
            return False
        if target_uid in source_named_view_uids:
            return target_uid in ref_remap.namedview_uids
        return target_uid in existing_named_view_uids

    def _update_named_view_names(self, updates: list) -> None:
        renames = [
            (str(uid), str(properties["Text"] or ""))
            for uid, ann_type, properties in updates
            if ann_type == ANNOTATION_TYPE_NAMED_VIEW and "Text" in properties
        ]
        if not renames:
            return
        self._data_svc.update_named_view_names(renames)

    def apply_default_annotation_layer(self, specs: List[InsertAnnotationSpec]) -> None:
        factory = AnnotationCreationFactory(self._data_svc.get_annotation_layer_uid())
        factory.assign_default_layer_to_specs(specs)

    def project_inserted_annotations(
        self,
        new_uids: List[str],
        specs: List[InsertAnnotationSpec],
        *,
        ref_remap: Optional[PasteRefRemap] = None,
    ) -> None:
        if not new_uids:
            return
        complete_uids = self._require_complete_identity_batch(new_uids, len(specs))
        self._add_inserted_annotations_to_model(
            complete_uids,
            specs,
            ref_remap=ref_remap,
        )
        self.publish_annotations_changed_for_pages(
            self._annotation_page_uids_for_specs(specs),
            complete_uids,
            self._annotation_types_from_specs(specs),
        )

    def project_deleted_annotations(
        self,
        annotation_keys: List[tuple[str, str]],
        *,
        page_uids: Optional[List[str]] = None,
    ) -> None:
        if not annotation_keys:
            return
        affected_pages = self._data_svc.remove_annotations_by_keys(annotation_keys)
        if page_uids:
            affected_pages = self._unique_ordered((*affected_pages, *page_uids))
        self.publish_annotations_changed_for_pages(
            affected_pages,
            [uid for uid, _annotation_type in annotation_keys],
            [annotation_type for _uid, annotation_type in annotation_keys],
        )

    def _add_inserted_annotations_to_model(
        self,
        new_uids: List[str],
        specs: List[InsertAnnotationSpec],
        ref_remap: Optional[PasteRefRemap] = None,
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
                    properties=(
                        ref_remap.remap_annotation_properties(spec.properties)
                        if ref_remap is not None
                        else dict(spec.properties)
                    ),
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
    def annotation_with_uid(
        annotation: BidAnnotation,
        uid: str,
        ref_remap: PasteRefRemap,
    ) -> BidAnnotation:
        return BidAnnotation(
            uid=str(uid),
            annotation_type=annotation.annotation_type,
            page_uid=annotation.page_uid,
            layer_uid=annotation.layer_uid,
            position=list(annotation.position),
            color=annotation.color,
            width=annotation.width,
            properties=ref_remap.remap_annotation_properties(annotation.properties),
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
        affected_page_uids = self._unique_ordered(page_uids)
        if not affected_page_uids:
            return
        payload = {
            "page_uid": affected_page_uids[0] if len(affected_page_uids) == 1 else "",
            "annotation_uids": list(annotation_uids),
            "annotation_types": list(event_types),
        }
        if len(affected_page_uids) > 1:
            payload["page_uids"] = affected_page_uids
        self._event_bus.publish(AppEvents.ANNOTATIONS_CHANGED, **payload)
