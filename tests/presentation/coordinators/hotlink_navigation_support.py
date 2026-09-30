import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from ost_visualizer.domain.entities.annotation import BidAnnotation
from ost_visualizer.presentation.config import TAB_INDEX_TAKEOFF


def _named_view_annotation(uid: str, name: str) -> BidAnnotation:
    return BidAnnotation(
        uid=uid,
        annotation_type="namedview",
        page_uid="p1",
        position=[13.0, 14.0, 1.0, 2.0, 13.0, 2.0, 1.0, 14.0, 0.0],
        properties={"Text": name},
    )


def _hotlink_annotation(uid: str, target_named_view_uid: str) -> BidAnnotation:
    return BidAnnotation(
        uid=uid,
        annotation_type="hotlink",
        page_uid="p1",
        position=[5.0, 6.0],
        properties={"BidPageViewUID": target_named_view_uid},
    )


def _rect_annotation(uid: str) -> BidAnnotation:
    return BidAnnotation(
        uid=uid,
        annotation_type="rect",
        page_uid="p1",
        position=[1.0, 2.0, 3.0, 4.0],
    )


class FakeHotlinkPlanView:
    def __init__(self, *, visible: bool = True, stable: bool = True):
        self.current_page_uid = None
        self._visible = visible
        self._stable = stable
        self.deferred_states = []
        self.reveals = 0
        self.zoom_rects = []

    @property
    def is_view_state_stable(self):
        return self._stable

    def isVisible(self):
        return self._visible

    def set_page_visual_reveal_deferred(self, deferred):
        self.deferred_states.append(bool(deferred))

    def reveal_deferred_page_visual(self):
        self.reveals += 1

    def zoom_to_rect(self, min_x, min_y, max_x, max_y, margin):
        self.zoom_rects.append((min_x, min_y, max_x, max_y, margin))


class FakeHotlinkViewer:
    def __init__(self, plan_view):
        self.plan_view = plan_view
        self.updated_pages = []
        self.annotation_updates = []

    def update_plan_view(
        self,
        page_uid,
        changed_takeoff_uids=None,
        changed_annotation_uids=None,
        changed_annotation_types=None,
    ):
        _ = changed_takeoff_uids
        self.annotation_updates.append(
            (page_uid, changed_annotation_uids, changed_annotation_types)
        )
        self.updated_pages.append(page_uid)
        self.plan_view.current_page_uid = page_uid


class FakeHotlinkSidebar:
    def __init__(self):
        self.quantity_updates = 0

    def update_conditions_quantities(self):
        self.quantity_updates += 1


class FakeHotlinkTabWidget:
    def currentIndex(self):
        return TAB_INDEX_TAKEOFF
