import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from ost_visualizer.presentation.managers.ui_access_manager import (
    PlanSurfaceAccessState,
)


def _full_plan_surface_access() -> PlanSurfaceAccessState:
    return PlanSurfaceAccessState(
        can_select_plan_items=True,
        can_place_plan_items=True,
        can_edit_plan_items=True,
        can_place_annotations=True,
        can_continue_annotation_placement=True,
        can_edit_annotations=True,
        can_edit_annotation_text=True,
        can_edit_page_settings=True,
    )


class FakePlanSurfaceAccessManager:
    def __init__(self, state=None):
        self.state = state or PlanSurfaceAccessState()
        self.listeners = []
        self.contexts = []
        self.interactions = {}

    def get_plan_surface_access(self, context):
        self.contexts.append(context)
        return self.state

    def subscribe_access_state_changed(self, callback):
        if callback not in self.listeners:
            self.listeners.append(callback)

    def unsubscribe_access_state_changed(self, callback):
        if callback in self.listeners:
            self.listeners.remove(callback)

    def clear_plan_surface_interaction(self, surface_id):
        if self.interactions.pop(surface_id, None) is None:
            return
        for callback in list(self.listeners):
            callback()

    def set_area_placement_active(self, active, *, surface_id):
        current = self.interactions.get(surface_id, (False, False))
        updated = (bool(active), current[1])
        if any(updated):
            self.interactions[surface_id] = updated
        else:
            self.interactions.pop(surface_id, None)
        for callback in list(self.listeners):
            callback()

    def set_text_annotation_edit_active(self, active, *, surface_id):
        current = self.interactions.get(surface_id, (False, False))
        updated = (current[0], bool(active))
        if any(updated):
            self.interactions[surface_id] = updated
        else:
            self.interactions.pop(surface_id, None)
        for callback in list(self.listeners):
            callback()

    def notify(self):
        for callback in list(self.listeners):
            callback()
