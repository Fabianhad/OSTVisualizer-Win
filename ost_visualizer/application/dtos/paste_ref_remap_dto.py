from dataclasses import dataclass, field
from typing import Dict, Mapping


@dataclass
class PasteRefRemap:
    takeoff_uids: Dict[str, str] = field(default_factory=dict)
    namedview_uids: Dict[str, str] = field(default_factory=dict)

    def is_empty(self) -> bool:
        return not self.takeoff_uids and not self.namedview_uids

    def remap_annotation_properties(
        self, properties: Mapping[str, object]
    ) -> Dict[str, object]:
        remapped_properties = dict(properties)
        for key in ("BidTakeoffFromUID", "BidTakeoffToUID"):
            raw_uid = remapped_properties.get(key)
            if raw_uid in (None, "", "0", 0):
                remapped_properties.pop(key, None)
                continue
            remapped_uid = self.takeoff_uids.get(str(raw_uid))
            if remapped_uid is None:
                remapped_properties.pop(key, None)
            else:
                remapped_properties[key] = str(remapped_uid)
        page_view_uid = remapped_properties.get("BidPageViewUID")
        if page_view_uid in (None, "", "0", 0):
            if "BidPageViewUID" in remapped_properties:
                remapped_properties["BidPageViewUID"] = None
        else:
            remapped_uid = self.namedview_uids.get(str(page_view_uid))
            if remapped_uid is not None:
                remapped_properties["BidPageViewUID"] = str(remapped_uid)
        return remapped_properties
