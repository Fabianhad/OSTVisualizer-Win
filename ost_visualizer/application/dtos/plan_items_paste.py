from copy import deepcopy
from dataclasses import replace
from ...domain.entities.annotation import (
    ANNOTATION_TYPE_HOTLINK,
    ANNOTATION_TYPE_NAMED_VIEW,
)
from .collaboration_dtos import PlanItemsPastePayload
from .collaboration_resource_catalog import parse_annotation_resource_id


def prepare_plan_items_paste_payload(
    payload: PlanItemsPastePayload,
) -> PlanItemsPastePayload:
    payload = deepcopy(payload)
    if payload.source_bid_uid == payload.destination_bid_uid:
        return payload
    copied_named_view_uids = {
        parse_annotation_resource_id(source_uid)[1]
        for source_uid in payload.annotation_source_uids
        if parse_annotation_resource_id(source_uid)[0] == ANNOTATION_TYPE_NAMED_VIEW
    }
    normalized_specs = []
    changed = False
    for spec in payload.annotation_specs:
        target_uid = spec.properties.get("BidPageViewUID")
        if (
            spec.annotation_type == ANNOTATION_TYPE_HOTLINK
            and target_uid not in (None, "", 0, "0")
            and str(target_uid) not in copied_named_view_uids
        ):
            properties = dict(spec.properties)
            properties["BidPageViewUID"] = None
            spec = replace(spec, properties=properties)
            changed = True
        normalized_specs.append(spec)
    return (
        replace(payload, annotation_specs=tuple(normalized_specs))
        if changed
        else payload
    )
