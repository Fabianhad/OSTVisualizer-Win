from dataclasses import dataclass
from typing import Callable, Iterable, List, Mapping
from ...domain.entities.annotation import ANNOTATION_TYPE_NAMED_VIEW

NAMED_VIEW_HOTLINK_DELETE_MESSAGE = (
    "This named view has hotlinks connected to it.\n"
    "Do you want to delete it and the associated hotlinks?"
)


def order_annotations_for_delete(annotations: Iterable) -> List:
    def rank(annotation) -> int:
        if annotation.is_hotlink:
            return 0
        if annotation.is_namedview:
            return 2
        return 1

    return sorted(list(annotations), key=rank)


@dataclass(frozen=True)
class NamedViewDeletePlan:
    annotations_to_delete: List
    skipped_named_view_uids: set[str]


def plan_named_view_hotlink_delete(
    annotations: Iterable,
    linked_hotlink_resolver: Callable[[set[str]], List],
    confirm_named_view_delete: Callable[[object], bool],
) -> NamedViewDeletePlan:
    annotations_to_delete = list(annotations)
    named_views = [
        annotation for annotation in annotations_to_delete if annotation.is_namedview
    ]
    if not named_views:
        return NamedViewDeletePlan(
            order_annotations_for_delete(annotations_to_delete), set()
        )
    linked_hotlinks = linked_hotlink_resolver(
        {str(annotation.uid) for annotation in named_views}
    )
    hotlinks_by_named_view: dict[str, List] = {}
    for hotlink in linked_hotlinks:
        target_uid = hotlink.hotlink_target_view_uid
        if target_uid:
            hotlinks_by_named_view.setdefault(str(target_uid), []).append(hotlink)
    skipped_named_view_uids: set[str] = set()
    confirmed_named_view_uids: set[str] = set()
    for annotation in named_views:
        uid = str(annotation.uid)
        if not hotlinks_by_named_view.get(uid) or confirm_named_view_delete(annotation):
            confirmed_named_view_uids.add(uid)
            continue
        skipped_named_view_uids.add(uid)
    annotations_to_delete = [
        annotation
        for annotation in annotations_to_delete
        if not (
            annotation.is_namedview and str(annotation.uid) in skipped_named_view_uids
        )
    ]
    existing_keys = {
        (str(annotation.uid), str(annotation.annotation_type))
        for annotation in annotations_to_delete
    }
    for named_view_uid in confirmed_named_view_uids:
        for hotlink in hotlinks_by_named_view.get(named_view_uid, []):
            key = (str(hotlink.uid), str(hotlink.annotation_type))
            if key in existing_keys:
                continue
            annotations_to_delete.append(hotlink)
            existing_keys.add(key)
    return NamedViewDeletePlan(
        order_annotations_for_delete(annotations_to_delete),
        skipped_named_view_uids,
    )


def skipped_named_view_selection_keys(
    annotation_selection_keys: Mapping[tuple[str, str], str],
    skipped_named_view_uids: set[str],
) -> set[str]:
    return {
        selection_key
        for (annotation_uid, annotation_type), selection_key in (
            annotation_selection_keys.items()
        )
        if annotation_uid in skipped_named_view_uids
        and annotation_type == ANNOTATION_TYPE_NAMED_VIEW
    }
