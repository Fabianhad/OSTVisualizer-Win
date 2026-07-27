from enum import Enum, auto
from typing import Callable, Optional
from ..managers.ui_access_manager import Feature
from .navigation_state_machine import NavState


class PlacementState(Enum):
    IDLE = auto()
    READY = auto()
    AREA_IN_PROGRESS = auto()


class PlacementCoordinator:
    def __init__(
        self, ui_state_manager, ui_access_manager, color_service, project_data
    ):
        self._ui_state = ui_state_manager
        self._access = ui_access_manager
        self._color_service = color_service
        self._project_data = project_data
        self._plan_view = None
        self._state = PlacementState.IDLE
        self._nav = None
        self._area_placement_in_progress = False
        self._state_change_callback: Optional[Callable[[], None]] = None

    def set_nav(self, nav) -> None:
        self._nav = nav

    def set_area_state_change_callback(
        self, callback: Optional[Callable[[], None]]
    ) -> None:
        self._state_change_callback = callback

    @property
    def state(self) -> PlacementState:
        return self._state

    @property
    def is_active(self) -> bool:
        return self._state != PlacementState.IDLE

    @property
    def condition_uid(self) -> Optional[str]:
        return self._ui_state.place_condition_uid

    def set_plan_view(self, view) -> None:
        prev = self._plan_view
        if prev:
            self._disconnect_plan_view(prev)
        self._plan_view = view
        if view:
            view.place_exited.connect(self._on_place_exited)
            view.area_placement_in_progress.connect(self._on_area_placement_changed)

    def enter(self, condition_uid: str, condition_uids: list) -> bool:
        if not self._plan_view:
            return False
        if not self._access.is_allowed(Feature.PLACE_PLAN_ITEMS):
            return False
        if not self._has_active_page_context():
            self.force_exit()
            return False
        if not self._is_condition_placeable(condition_uid):
            self.force_exit()
            return False
        condition_uids = self._normalize_place_condition_uids(
            condition_uid, condition_uids
        )
        self._ui_state.set_place_condition_uids(condition_uids)
        self._ensure_color_map_includes(condition_uids)
        activated = self._plan_view.activate_place_for_condition(
            condition_uid, condition_uids
        )
        if not activated:
            self._ui_state.clear_place_condition()
            return False
        self._ui_state.place_condition_uid = condition_uid
        self._state = PlacementState.READY
        if self._nav:
            self._nav.transition_to(NavState.PLACE_MODE)
        return True

    def exit(self) -> None:
        if self._state == PlacementState.IDLE:
            return
        if self._plan_view:
            self._plan_view.cancel_place_mode()
        self._finalize_exit()

    def force_exit(self) -> None:
        if self._plan_view:
            self._plan_view.cancel_place_mode()
        self._finalize_exit()

    def _on_place_exited(self) -> None:
        self._finalize_exit()

    def _on_area_placement_changed(self, in_progress: bool) -> None:
        in_progress = bool(in_progress)
        if self._area_placement_in_progress == in_progress:
            return
        self._area_placement_in_progress = in_progress
        if in_progress and self._state == PlacementState.READY:
            self._state = PlacementState.AREA_IN_PROGRESS
        elif not in_progress and self._state == PlacementState.AREA_IN_PROGRESS:
            self._state = PlacementState.READY
        self._access.set_area_placement_active(in_progress)
        if self._state_change_callback:
            self._state_change_callback()

    def _finalize_exit(self) -> None:
        if self._state == PlacementState.IDLE:
            return
        self._state = PlacementState.IDLE
        self._ui_state.clear_place_condition()
        if self._area_placement_in_progress:
            self._on_area_placement_changed(False)
        if self._nav and self._nav.current_state == NavState.PLACE_MODE:
            self._nav.transition_to(NavState.BID_ACTIVE_PAGES_SELECTED)

    def _is_condition_placeable(self, condition_uid: str) -> bool:
        condition = self._project_data.get_bid_conditions().get(condition_uid)
        return bool(condition and condition.layer_visible)

    def _has_active_page_context(self) -> bool:
        if not self._ui_state.active_page_uid:
            return False
        if self._nav and self._nav.current_state not in (
            NavState.BID_ACTIVE_PAGES_SELECTED,
            NavState.PLACE_MODE,
        ):
            return False
        return True

    def _normalize_place_condition_uids(
        self, active_uid: str, condition_uids: list
    ) -> list:
        ordered = []
        seen = set()
        for uid in list(condition_uids or []) + [active_uid]:
            if not uid or uid in seen or not self._is_condition_placeable(uid):
                continue
            ordered.append(uid)
            seen.add(uid)
        return ordered

    def _ensure_color_map_includes(self, condition_uids: list) -> None:
        conditions = self._project_data.get_bid_conditions()
        extra_condition_uids = {uid for uid in condition_uids if uid in conditions}
        if not extra_condition_uids:
            return
        page_uid = self._ui_state.active_page_uid
        if not page_uid:
            return
        page_takeoffs = self._project_data.get_page_takeoffs(page_uid)
        display_mode = self._ui_state.state.display_mode_2d
        grayscale_enabled = self._ui_state.state.grayscale_enabled
        _, color_map = self._color_service.get_color_mapping(
            conditions,
            page_takeoffs,
            display_mode,
            grayscale_enabled,
            extra_condition_uids=extra_condition_uids,
        )
        self._plan_view.update_color_map(color_map)

    def _disconnect_plan_view(self, view) -> None:
        connections = (
            (view.place_exited, self._on_place_exited),
            (view.area_placement_in_progress, self._on_area_placement_changed),
        )
        for signal, callback in connections:
            try:
                signal.disconnect(callback)
            except RuntimeError:
                pass

    def cleanup(self) -> None:
        if self._plan_view:
            self._disconnect_plan_view(self._plan_view)
        self._plan_view = None
        self._nav = None
        self._state_change_callback = None
        self._ui_state = None
        self._access = None
        self._color_service = None
        self._project_data = None
