import hashlib
import json
from dataclasses import asdict
from typing import Dict, Iterable

TOKEN_CLOSED = "closed"
TOKEN_MISSING = "missing"
TOKEN_UNKNOWN = "unknown"
_PAGE_FIELDS = (
    "scale_factor1",
    "scale_factor2",
    "image_path",
    "page_index",
    "width_pts",
    "height_pts",
    "overlay_image_path",
)


def _digest(value) -> str:
    text = json.dumps(value, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


class ProjectDataTokenReader:
    def __init__(self, project_data):
        self._project_data = project_data

    def __call__(
        self, database_id: str, bid_uid: str, resources: Iterable[str]
    ) -> Dict[str, str]:
        resources = tuple(resources)
        bid_ref = self._project_data.get_current_bid_ref()
        if (
            bid_ref is None
            or str(bid_ref.file_path) != str(database_id)
            or str(bid_ref.bid_uid) != str(bid_uid)
        ):
            return {resource: TOKEN_CLOSED for resource in resources}
        return {resource: self._token(resource) for resource in resources}

    def _token(self, resource: str) -> str:
        kind, _separator, uid = resource.partition(":")
        if kind == "page":
            page = self._project_data.get_page(uid)
            if page is None:
                return TOKEN_MISSING
            values = asdict(page)
            return _digest({name: values.get(name) for name in _PAGE_FIELDS})
        if kind == "page_takeoffs":
            takeoffs = self._project_data.get_page_takeoffs(uid)
            return _digest(
                sorted(
                    (str(item.uid), str(item.condition_uid), list(item.position))
                    for item in takeoffs
                )
            )
        if kind == "takeoff":
            for takeoff in self._project_data.get_all_takeoffs():
                if str(takeoff.uid) == uid:
                    return _digest(asdict(takeoff))
            return TOKEN_MISSING
        if kind == "condition_takeoffs":
            return _digest(
                sorted(
                    str(takeoff.uid)
                    for takeoff in self._project_data.get_all_takeoffs()
                    if str(takeoff.condition_uid) == uid
                )
            )
        if kind == "condition":
            condition = self._project_data.get_bid_conditions().get(uid)
            if condition is None:
                return TOKEN_MISSING
            return _digest(asdict(condition))
        return TOKEN_UNKNOWN
