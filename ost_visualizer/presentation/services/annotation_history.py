from dataclasses import replace
from ...domain.services.page_scale_transform import (
    rescale_annotation_position_between_page_scales,
)
from .undo_redo_service import AnnotationHistoryTarget


def capture_annotation_targets(data, bid_ref, updates):
    annotations = {
        (str(item.uid), item.annotation_type): item
        for item in data.get_all_annotations()
    }
    targets = {}
    for uid, kind, *_values in updates:
        key = (str(uid), str(kind))
        annotation = annotations.get(key)
        if annotation is None:
            raise ValueError("The history Annotation is no longer authoritative.")
        targets[key] = AnnotationHistoryTarget(
            bid_ref, str(annotation.page_uid), str(kind), str(uid)
        )
    return targets


def resolve_annotation_updates(data, updates, targets):
    if not targets:
        return updates
    annotations = {
        (str(item.uid), item.annotation_type): item
        for item in data.get_all_annotations()
    }
    for target in targets.values():
        annotation = annotations.get((target.uid, target.annotation_type))
        if (
            not target.available
            or annotation is None
            or str(annotation.page_uid) != target.page_uid
            or data.get_current_bid_ref() != target.bid_ref
        ):
            raise ValueError("The history Annotation no longer owns its Page.")
    return [
        (targets[(str(uid), str(kind))].uid, kind, *values)
        for uid, kind, *values in updates
    ]


class AnnotationHistoryBinding:
    def __init__(self, data, undo, bid_ref, targets):
        self._data = data
        self._undo = undo
        self.bid_ref = bid_ref
        self.targets = targets
        self._suspended = ()
        self._scales = {
            target.page_uid: self._page_scale(target.page_uid)
            for target in targets.values()
        }

    def _page_scale(self, page_uid):
        page = self._data.get_page(page_uid)
        if page is None:
            raise ValueError("The history Annotation Page no longer exists.")
        return (float(page.scale_factor1 or 1.0), float(page.scale_factor2 or 1.0))

    def updates(self, updates):
        return resolve_annotation_updates(self._data, updates, self.targets)

    def keys(self):
        return self.updates(list(self.targets))

    def positions(self, positions):
        resolved = self.updates(positions)
        return [
            (uid, kind, self._position(target, position))
            for (uid, kind, position), target in zip(
                resolved,
                (self.targets[(str(uid), str(kind))] for uid, kind, _ in positions),
            )
        ]

    def _position(self, target, position):
        return rescale_annotation_position_between_page_scales(
            target.annotation_type,
            position,
            self._scales[target.page_uid],
            self._page_scale(target.page_uid),
        )

    def specs(self, specs):
        return [
            replace(spec, position=self._position(target, spec.position))
            for spec, target in zip(specs, self.targets.values())
        ]

    def saved_annotations(self, annotations, *, restoring=False):
        if not restoring:
            self.keys()
        return [
            replace(
                annotation,
                uid=annotation.uid if restoring else target.uid,
                position=self._position(target, annotation.position),
            )
            for annotation, target in zip(annotations, self.targets.values())
        ]

    def suspend(self):
        self._suspended = self._undo.suspend_deleted_annotations(
            self.bid_ref, tuple(self.targets.values())
        )

    def rebind(self, uids):
        if len(uids) != len(self.targets):
            raise ValueError("Annotation restore returned an incomplete identity map.")
        self._undo.rebind_restored_annotations(
            self.bid_ref,
            {
                target.identity: str(uid)
                for target, uid in zip(self.targets.values(), uids)
            },
            self._suspended,
        )
