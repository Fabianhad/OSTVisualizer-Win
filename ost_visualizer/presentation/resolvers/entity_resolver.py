from typing import Optional
from ...domain.entities.takeoff import Takeoff


class EntityResolver:
    def __init__(self, plan_view, project_data_svc) -> None:
        self._plan_view = plan_view
        self._data_svc = project_data_svc

    def set_plan_view(self, plan_view) -> None:
        self._plan_view = plan_view

    def resolve_takeoff(self, uid: str) -> Optional[Takeoff]:
        if self._plan_view:
            t = self._plan_view.get_takeoff(uid)
            if t:
                return t
        return self._data_svc.get_takeoff(uid)
