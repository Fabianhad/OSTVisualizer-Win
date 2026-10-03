from dataclasses import replace
from ...domain.entities.annotation import (
    ANNOTATION_TYPE_HOTLINK,
    ANNOTATION_TYPE_NAMED_VIEW,
)
from ...domain.services.page_scale_transform import (
    rescale_annotation_position_between_page_scales,
)
from .undo_redo_service import AnnotationHistoryTarget

HOTLINK_VIEW_UNAVAILABLE_MESSAGE = (
    "A Hot Link cannot be restored because the Named View it points to is no "
    "longer the same Named View: it was deleted without being restored, or "
    "another Named View took its place."
)


class AnnotationHistoryDependencyError(ValueError):
    """A retained history dependency cannot be proven to be the same object."""


def _annotation_page_scale(data, page_uid):
    page = data.get_page(page_uid)
    if page is None:
        raise ValueError("The history Annotation Page no longer exists.")
    return (float(page.scale_factor1 or 1.0), float(page.scale_factor2 or 1.0))


def capture_annotation_page_scales(data, page_uids):
    return {str(uid): _annotation_page_scale(data, str(uid)) for uid in page_uids}


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


def capture_hotlink_view_dependencies(data, bid_ref, items, batch_named_view_uids=()):
    batch = {str(uid) for uid in batch_named_view_uids}
    named_views = None
    shared = {}
    dependencies = []
    for item in items:
        target_uid = (
            item.properties.get("BidPageViewUID")
            if item.annotation_type == ANNOTATION_TYPE_HOTLINK
            else None
        )
        key = str(target_uid)
        if target_uid in (None, "", 0, "0") or key in batch:
            dependencies.append(None)
            continue
        if key not in shared:
            if named_views is None:
                named_views = {
                    str(annotation.uid): annotation
                    for annotation in data.get_all_annotations()
                    if annotation.annotation_type == ANNOTATION_TYPE_NAMED_VIEW
                }
            view = named_views.get(key)
            shared[key] = (
                None
                if view is None
                else AnnotationHistoryTarget(
                    bid_ref, str(view.page_uid), ANNOTATION_TYPE_NAMED_VIEW, key
                )
            )
        dependencies.append(shared[key])
    return tuple(dependencies)


def retained_hotlink_view_targets(dependencies):
    return tuple(
        {id(target): target for target in dependencies if target is not None}.values()
    )


def resolve_hotlink_view_targets(data, items, dependencies):
    resolved = list(items)
    named_views = None
    for index, dependency in enumerate(dependencies[: len(resolved)]):
        if dependency is None:
            continue
        if named_views is None:
            named_views = {
                (str(annotation.uid), str(annotation.page_uid))
                for annotation in data.get_all_annotations()
                if annotation.annotation_type == ANNOTATION_TYPE_NAMED_VIEW
            }
        if (
            not dependency.available
            or data.get_current_bid_ref() != dependency.bid_ref
            or (dependency.uid, dependency.page_uid) not in named_views
        ):
            raise AnnotationHistoryDependencyError(HOTLINK_VIEW_UNAVAILABLE_MESSAGE)
        item = resolved[index]
        resolved[index] = replace(
            item, properties={**item.properties, "BidPageViewUID": dependency.uid}
        )
    return resolved


class AnnotationHistoryBinding:
    def __init__(
        self,
        data,
        undo,
        bid_ref,
        targets,
        *,
        captured_scales=None,
        view_dependencies=(),
    ):
        self._data = data
        self.view_dependencies = tuple(view_dependencies)
        self._undo = undo
        self.bid_ref = bid_ref
        self.targets = targets
        self._suspended = ()
        self._scales = (
            dict(captured_scales)
            if captured_scales is not None
            else {
                target.page_uid: self._page_scale(target.page_uid)
                for target in targets.values()
            }
        )

    def _page_scale(self, page_uid):
        return _annotation_page_scale(self._data, page_uid)

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

    def history_targets(self):
        return (
            *self.targets.values(),
            *retained_hotlink_view_targets(self.view_dependencies),
        )

    def specs(self, specs):
        return resolve_hotlink_view_targets(
            self._data,
            [
                replace(spec, position=self._position(target, spec.position))
                for spec, target in zip(specs, self.targets.values())
            ],
            self.view_dependencies,
        )

    def saved_annotations(self, annotations, *, restoring=False):
        if not restoring:
            self.keys()
        saved = [
            replace(
                annotation,
                uid=annotation.uid if restoring else target.uid,
                position=self._position(target, annotation.position),
            )
            for annotation, target in zip(annotations, self.targets.values())
        ]
        if restoring:
            return resolve_hotlink_view_targets(
                self._data, saved, self.view_dependencies
            )
        return saved

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
