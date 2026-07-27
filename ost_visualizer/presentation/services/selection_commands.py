from copy import deepcopy
from typing import Any, Callable, Dict, List, Optional
from ...application.dtos.insert_annotation_spec_dto import InsertAnnotationSpec
from ...application.dtos.insert_takeoff_spec_dto import InsertTakeoffSpec
from ...application.dtos.paste_ref_remap_dto import PasteRefRemap
from ...domain.entities.identity_refs import BidRef

TakeoffInsertFn = Callable[[BidRef, List[InsertTakeoffSpec]], List[str]]
TakeoffDeleteFn = Callable[[str, List[str]], bool]
AnnotationInsertFn = Callable[
    [BidRef, List[InsertAnnotationSpec], Optional[PasteRefRemap]], List[str]
]
AnnotationDeleteFn = Callable[[str, List[str], List[InsertAnnotationSpec]], bool]
SavedAnnotationInsertFn = Callable[[BidRef, list], list]
SavedAnnotationDeleteFn = Callable[[str, list], bool]
TakeoffSpecsPrepareFn = Callable[[List[InsertTakeoffSpec]], List[InsertTakeoffSpec]]
AnnotationSpecsPrepareFn = Callable[
    [List[InsertAnnotationSpec]], List[InsertAnnotationSpec]
]


def _identity_takeoff_specs(
    specs: List[InsertTakeoffSpec],
) -> List[InsertTakeoffSpec]:
    return specs


def _identity_annotation_specs(
    specs: List[InsertAnnotationSpec],
) -> List[InsertAnnotationSpec]:
    return specs


def _require_complete_takeoff_insert(
    inserted_uids: List[str], expected_count: int
) -> List[str]:
    result = list(inserted_uids)
    if len(result) != expected_count:
        raise ValueError(
            "Takeoff insert returned "
            f"{len(result)} identities for {expected_count} requested takeoffs"
        )
    return result


def _default_insert_takeoffs(write_svc) -> TakeoffInsertFn:
    def _insert(bid_ref: BidRef, specs: List[InsertTakeoffSpec]) -> List[str]:
        return write_svc.insert_takeoffs(bid_ref.file_path, bid_ref.bid_uid, specs)

    return _insert


def _default_delete_takeoffs(write_svc) -> TakeoffDeleteFn:
    def _delete(db_path: str, uids: List[str]) -> bool:
        return write_svc.delete_takeoffs(db_path, uids)

    return _delete


def _default_insert_annotations(write_svc) -> AnnotationInsertFn:
    def _insert(
        bid_ref: BidRef,
        specs: List[InsertAnnotationSpec],
        ref_remap: Optional[PasteRefRemap],
    ) -> List[str]:
        return write_svc.insert_annotations(
            bid_ref.file_path,
            bid_ref.bid_uid,
            specs,
            ref_remap=ref_remap,
        )

    return _insert


def _default_delete_annotations(write_svc) -> AnnotationDeleteFn:
    def _delete(
        db_path: str, uids: List[str], specs: List[InsertAnnotationSpec]
    ) -> bool:
        return write_svc.delete_annotations(
            db_path,
            [(uid, spec.annotation_type) for uid, spec in zip(uids, specs)],
        )

    return _delete


class InsertTakeoffsCommand:
    def __init__(
        self,
        uids: List[str],
        bid_ref: BidRef,
        specs: list,
        write_svc,
        plan_view,
        insert_takeoffs_fn: Optional[TakeoffInsertFn] = None,
        delete_takeoffs_fn: Optional[TakeoffDeleteFn] = None,
        prepare_specs_fn: Optional[TakeoffSpecsPrepareFn] = None,
    ) -> None:
        self._current_uids = list(uids)
        self._bid_ref = bid_ref
        self._specs = list(specs)
        self._write_svc = write_svc
        self._plan_view = plan_view
        self._insert_takeoffs_fn = insert_takeoffs_fn or _default_insert_takeoffs(
            write_svc
        )
        self._delete_takeoffs_fn = delete_takeoffs_fn or _default_delete_takeoffs(
            write_svc
        )
        self._prepare_specs_fn = prepare_specs_fn or _identity_takeoff_specs

    def undo(self) -> None:
        if self._delete_takeoffs_fn(self._bid_ref.file_path, list(self._current_uids)):
            self._plan_view.clear_selection()

    def redo(self) -> None:
        prepared_specs = self._prepare_specs_fn(self._specs)
        new_uids = _require_complete_takeoff_insert(
            self._insert_takeoffs_fn(self._bid_ref, prepared_specs),
            len(self._specs),
        )
        for i, uid in enumerate(new_uids):
            self._current_uids[i] = uid
        if new_uids:
            self._plan_view.set_selected_uids(set(new_uids))


class InsertAnnotationsCommand:
    def __init__(
        self,
        uids: List[str],
        bid_ref: BidRef,
        specs: list,
        write_svc,
        plan_view,
        insert_annotations_fn: Optional[AnnotationInsertFn] = None,
        delete_annotations_fn: Optional[AnnotationDeleteFn] = None,
        prepare_specs_fn: Optional[AnnotationSpecsPrepareFn] = None,
    ) -> None:
        self._current_uids = list(uids)
        self._bid_ref = bid_ref
        self._specs = list(specs)
        self._write_svc = write_svc
        self._plan_view = plan_view
        self._insert_annotations_fn = (
            insert_annotations_fn or _default_insert_annotations(write_svc)
        )
        self._delete_annotations_fn = (
            delete_annotations_fn or _default_delete_annotations(write_svc)
        )
        self._prepare_specs_fn = prepare_specs_fn or _identity_annotation_specs

    def undo(self) -> None:
        if self._delete_annotations_fn(
            self._bid_ref.file_path, list(self._current_uids), self._specs
        ):
            self._plan_view.clear_selection()

    def redo(self) -> None:
        prepared_specs = self._prepare_specs_fn(self._specs)
        new_uids = self._insert_annotations_fn(self._bid_ref, prepared_specs, None)
        self._specs = self._specs[: len(new_uids)]
        self._current_uids = list(new_uids)
        if self._current_uids:
            uid_type_set = {
                (uid, self._specs[i].annotation_type)
                for i, uid in enumerate(self._current_uids)
            }
            keys = self._plan_view.find_annotation_keys_by_uid_type(uid_type_set)
            self._plan_view.set_selected_uids(keys)


def _takeoff_to_spec(
    t,
    source_bid_uid: Optional[str] = None,
    extras: Optional[Dict[str, Any]] = None,
) -> InsertTakeoffSpec:
    return InsertTakeoffSpec(
        condition_uid=t.condition_uid,
        page_uid=t.page_uid,
        area_uid=t.area_uid,
        position=list(t.position),
        parent_uid=t.parent_uid,
        curve=t.curve,
        rotation=t.rotation,
        is_negative=t.is_negative,
        raw_extras=dict(extras) if extras else {},
        source_bid_uid=source_bid_uid,
    )


def _insert_takeoffs_with_source_parent_remap(
    insert_takeoffs_fn: TakeoffInsertFn,
    bid_ref: BidRef,
    takeoffs: list,
    source_uids: List[str],
    source_parent_uids: List[str],
    source_bid_uid: Optional[str],
    takeoff_extras: Dict[str, Dict[str, Any]],
    prepare_specs_fn: Optional[TakeoffSpecsPrepareFn] = None,
) -> List[Optional[str]]:
    new_uids: List[Optional[str]] = [None] * len(takeoffs)
    source_to_new: Dict[str, str] = {}
    source_uid_set = {str(uid) for uid in source_uids}
    pending = set(range(len(takeoffs)))
    while pending:
        ready = [
            i
            for i in pending
            if str(source_parent_uids[i]) not in source_uid_set
            or str(source_parent_uids[i]) in source_to_new
        ]
        if not ready:
            raise ValueError("Cannot recreate takeoffs with cyclic parent references")
        specs = []
        for i in ready:
            source_uid = str(source_uids[i])
            source_parent_uid = str(source_parent_uids[i])
            spec = _takeoff_to_spec(
                takeoffs[i],
                source_bid_uid,
                takeoff_extras.get(source_uid),
            )
            if source_parent_uid in source_to_new:
                spec.parent_uid = source_to_new[source_parent_uid]
            specs.append(spec)
        prepared_specs = (prepare_specs_fn or _identity_takeoff_specs)(specs)
        inserted_uids = _require_complete_takeoff_insert(
            insert_takeoffs_fn(bid_ref, prepared_specs),
            len(ready),
        )
        for i, uid in zip(ready, inserted_uids):
            source_uid = str(source_uids[i])
            source_parent_uid = str(source_parent_uids[i])
            new_uids[i] = uid
            source_to_new[source_uid] = uid
            takeoffs[i].uid = uid
            if source_parent_uid in source_to_new:
                takeoffs[i].parent_uid = source_to_new[source_parent_uid]
        for i in ready:
            pending.discard(i)
    return new_uids


class DeleteTakeoffsCommand:
    def __init__(
        self,
        saved_takeoffs: list,
        bid_ref: BidRef,
        write_svc,
        plan_view,
        takeoff_extras: Optional[Dict[str, Dict[str, Any]]] = None,
        insert_takeoffs_fn: Optional[TakeoffInsertFn] = None,
        delete_takeoffs_fn: Optional[TakeoffDeleteFn] = None,
        prepare_specs_fn: Optional[TakeoffSpecsPrepareFn] = None,
    ) -> None:
        self._saved_takeoffs = deepcopy(saved_takeoffs)
        self._bid_ref = bid_ref
        self._write_svc = write_svc
        self._plan_view = plan_view
        self._source_bid_uid = bid_ref.bid_uid
        self._current_uids: List[str] = [t.uid for t in self._saved_takeoffs]
        self._source_uids: List[str] = [str(t.uid) for t in self._saved_takeoffs]
        self._source_parent_uids: List[str] = [
            str(t.parent_uid) for t in self._saved_takeoffs
        ]
        self._takeoff_extras: Dict[str, Dict[str, Any]] = {
            str(uid): dict(extras) for uid, extras in (takeoff_extras or {}).items()
        }
        self._insert_takeoffs_fn = insert_takeoffs_fn or _default_insert_takeoffs(
            write_svc
        )
        self._delete_takeoffs_fn = delete_takeoffs_fn or _default_delete_takeoffs(
            write_svc
        )
        self._prepare_specs_fn = prepare_specs_fn or _identity_takeoff_specs

    def undo(self) -> None:
        new_uids_by_index = _insert_takeoffs_with_source_parent_remap(
            self._insert_takeoffs_fn,
            self._bid_ref,
            self._saved_takeoffs,
            self._source_uids,
            self._source_parent_uids,
            self._source_bid_uid,
            self._takeoff_extras,
            self._prepare_specs_fn,
        )
        self._current_uids = [uid for uid in new_uids_by_index if uid is not None]
        new_uids = list(self._current_uids)
        if new_uids:
            self._plan_view.set_selected_uids(set(new_uids))

    def redo(self) -> None:
        if self._delete_takeoffs_fn(self._bid_ref.file_path, list(self._current_uids)):
            self._plan_view.clear_selection()


class PasteTakeoffsCommand:
    def __init__(
        self,
        pasted_takeoffs: list,
        bid_ref: BidRef,
        write_svc,
        plan_view,
        source_uids: List[str],
        source_parent_uids: List[str],
        source_bid_uid: Optional[str] = None,
        takeoff_extras: Optional[Dict[str, Dict[str, Any]]] = None,
        insert_takeoffs_fn: Optional[TakeoffInsertFn] = None,
        delete_takeoffs_fn: Optional[TakeoffDeleteFn] = None,
        prepare_specs_fn: Optional[TakeoffSpecsPrepareFn] = None,
    ) -> None:
        self._pasted_takeoffs = deepcopy(pasted_takeoffs)
        self._bid_ref = bid_ref
        self._write_svc = write_svc
        self._plan_view = plan_view
        self._source_bid_uid = source_bid_uid or bid_ref.bid_uid
        self._current_uids: List[str] = [t.uid for t in self._pasted_takeoffs]
        self._source_uids: List[str] = [str(uid) for uid in source_uids]
        self._source_parent_uids: List[str] = [str(uid) for uid in source_parent_uids]
        self._takeoff_extras: Dict[str, Dict[str, Any]] = {
            str(uid): dict(extras) for uid, extras in (takeoff_extras or {}).items()
        }
        self._insert_takeoffs_fn = insert_takeoffs_fn or _default_insert_takeoffs(
            write_svc
        )
        self._delete_takeoffs_fn = delete_takeoffs_fn or _default_delete_takeoffs(
            write_svc
        )
        self._prepare_specs_fn = prepare_specs_fn or _identity_takeoff_specs

    def get_uid_remap(self) -> Dict[str, str]:
        return {
            str(orig): str(current)
            for orig, current in zip(self._source_uids, self._current_uids)
        }

    def get_result_keys(self) -> set:
        return set(self._current_uids)

    def undo(self) -> None:
        if self._delete_takeoffs_fn(self._bid_ref.file_path, list(self._current_uids)):
            self._plan_view.clear_selection()

    def redo(self) -> None:
        new_uids_by_index = _insert_takeoffs_with_source_parent_remap(
            self._insert_takeoffs_fn,
            self._bid_ref,
            self._pasted_takeoffs,
            self._source_uids,
            self._source_parent_uids,
            self._source_bid_uid,
            self._takeoff_extras,
            self._prepare_specs_fn,
        )
        self._current_uids = [uid for uid in new_uids_by_index if uid is not None]
        new_uids = list(self._current_uids)
        if new_uids:
            self._plan_view.set_selected_uids(set(new_uids))


class DeleteAnnotationsCommand:
    def __init__(
        self,
        saved_annotations: list,
        bid_ref: BidRef,
        plan_view,
        insert_saved_annotations_fn: SavedAnnotationInsertFn,
        delete_saved_annotations_fn: SavedAnnotationDeleteFn,
    ) -> None:
        self._saved = deepcopy(saved_annotations)
        self._bid_ref = bid_ref
        self._plan_view = plan_view
        self._insert_saved_annotations_fn = insert_saved_annotations_fn
        self._delete_saved_annotations_fn = delete_saved_annotations_fn

    def undo(self) -> None:
        restored = self._insert_saved_annotations_fn(self._bid_ref, self._saved)
        if not restored:
            return
        self._saved = list(restored)
        uid_type_set = {
            (annotation.uid, annotation.annotation_type) for annotation in self._saved
        }
        keys = self._plan_view.find_annotation_keys_by_uid_type(uid_type_set)
        self._plan_view.set_selected_uids(keys)

    def redo(self) -> None:
        if self._delete_saved_annotations_fn(self._bid_ref.file_path, self._saved):
            self._plan_view.clear_selection()


class PasteAnnotationsCommand:
    def __init__(
        self,
        specs: list,
        new_uids: List[str],
        bid_ref: BidRef,
        write_svc,
        plan_view,
        sibling_takeoff_cmd: Optional[PasteTakeoffsCommand] = None,
        insert_annotations_fn: Optional[AnnotationInsertFn] = None,
        delete_annotations_fn: Optional[AnnotationDeleteFn] = None,
        prepare_specs_fn: Optional[AnnotationSpecsPrepareFn] = None,
    ) -> None:
        self._specs = list(specs)
        self._current_uids = list(new_uids)
        self._bid_ref = bid_ref
        self._write_svc = write_svc
        self._plan_view = plan_view
        self._sibling_takeoff_cmd = sibling_takeoff_cmd
        self._insert_annotations_fn = (
            insert_annotations_fn or _default_insert_annotations(write_svc)
        )
        self._delete_annotations_fn = (
            delete_annotations_fn or _default_delete_annotations(write_svc)
        )
        self._prepare_specs_fn = prepare_specs_fn or _identity_annotation_specs

    def get_result_keys(self) -> set:
        uid_type_set = {
            (uid, self._specs[i].annotation_type)
            for i, uid in enumerate(self._current_uids)
        }
        return self._plan_view.find_annotation_keys_by_uid_type(uid_type_set)

    def undo(self) -> None:
        if self._delete_annotations_fn(
            self._bid_ref.file_path, list(self._current_uids), self._specs
        ):
            self._plan_view.clear_selection()

    def redo(self) -> None:
        ref_remap = PasteRefRemap()
        if self._sibling_takeoff_cmd is not None:
            ref_remap.takeoff_uids.update(self._sibling_takeoff_cmd.get_uid_remap())
        prepared_specs = self._prepare_specs_fn(self._specs)
        new_uids = self._insert_annotations_fn(self._bid_ref, prepared_specs, ref_remap)
        self._specs = self._specs[: len(new_uids)]
        self._current_uids = list(new_uids)
        if self._current_uids:
            uid_type_set = {
                (uid, self._specs[i].annotation_type)
                for i, uid in enumerate(self._current_uids)
            }
            keys = self._plan_view.find_annotation_keys_by_uid_type(uid_type_set)
            self._plan_view.set_selected_uids(keys)
