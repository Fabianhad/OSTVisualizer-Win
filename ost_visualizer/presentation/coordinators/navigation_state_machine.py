import logging
from dataclasses import dataclass
from enum import Enum, auto
from typing import List, Optional, Set
from ...domain.entities.identity_refs import BidRef

logger = logging.getLogger(__name__)


class NavState(Enum):
    NO_FILE = auto()
    FILE_LOADED_NO_BID = auto()
    BID_ACTIVE_NO_PAGES = auto()
    BID_ACTIVE_PAGES_SELECTED = auto()
    PLACE_MODE = auto()
    REFRESHING = auto()


_VALID_TRANSITIONS = {
    NavState.NO_FILE: {
        NavState.NO_FILE,
        NavState.FILE_LOADED_NO_BID,
    },
    NavState.FILE_LOADED_NO_BID: {
        NavState.NO_FILE,
        NavState.FILE_LOADED_NO_BID,
        NavState.BID_ACTIVE_NO_PAGES,
        NavState.REFRESHING,
    },
    NavState.BID_ACTIVE_NO_PAGES: {
        NavState.NO_FILE,
        NavState.FILE_LOADED_NO_BID,
        NavState.BID_ACTIVE_NO_PAGES,
        NavState.BID_ACTIVE_PAGES_SELECTED,
        NavState.REFRESHING,
    },
    NavState.BID_ACTIVE_PAGES_SELECTED: {
        NavState.NO_FILE,
        NavState.FILE_LOADED_NO_BID,
        NavState.BID_ACTIVE_NO_PAGES,
        NavState.BID_ACTIVE_PAGES_SELECTED,
        NavState.PLACE_MODE,
        NavState.REFRESHING,
    },
    NavState.PLACE_MODE: {
        NavState.NO_FILE,
        NavState.FILE_LOADED_NO_BID,
        NavState.BID_ACTIVE_NO_PAGES,
        NavState.BID_ACTIVE_PAGES_SELECTED,
        NavState.PLACE_MODE,
        NavState.REFRESHING,
    },
    NavState.REFRESHING: set(),
}
_VALID_REFRESH_TARGETS = {
    NavState.NO_FILE,
    NavState.FILE_LOADED_NO_BID,
    NavState.BID_ACTIVE_NO_PAGES,
    NavState.BID_ACTIVE_PAGES_SELECTED,
    NavState.PLACE_MODE,
}


@dataclass
class RefreshSnapshot:
    bid_ref: Optional[BidRef]
    page_uids: List[str]
    active_page_uid: Optional[str]
    highlighted_condition_uids: Set[str]
    project_uid: Optional[str]
    database_selected: bool = False
    selected_file_path: Optional[str] = None
    place_condition_uid: Optional[str] = None
    place_condition_uids: List[str] = None
    selected_area_uid: str = ""

    def __post_init__(self):
        if self.place_condition_uids is None:
            self.place_condition_uids = []


class NavigationStateMachine:
    def __init__(self):
        self._state = NavState.NO_FILE
        self._transitioning = False
        self._refresh_snapshot: Optional[RefreshSnapshot] = None

    @property
    def current_state(self) -> NavState:
        return self._state

    @property
    def is_refreshing(self) -> bool:
        return self._state == NavState.REFRESHING

    @property
    def refresh_snapshot(self) -> Optional[RefreshSnapshot]:
        return self._refresh_snapshot

    def transition_to(self, target: NavState) -> bool:
        if self._transitioning:
            return False
        allowed = _VALID_TRANSITIONS.get(self._state, set())
        if target not in allowed:
            logger.warning(
                "Invalid transition %s -> %s",
                self._state.name,
                target.name,
            )
            return False
        self._transitioning = True
        self._state = target
        self._transitioning = False
        return True

    def compute_state_for(
        self,
        has_file: bool,
        bid_ref: Optional[BidRef],
        active_page_uid: Optional[str],
    ) -> NavState:
        if not has_file:
            return NavState.NO_FILE
        if not bid_ref:
            return NavState.FILE_LOADED_NO_BID
        if not active_page_uid:
            return NavState.BID_ACTIVE_NO_PAGES
        return NavState.BID_ACTIVE_PAGES_SELECTED

    def start_refresh(self, ui_state, placement, selected_area_uid: str = "") -> bool:
        if not self.transition_to(NavState.REFRESHING):
            return False
        self._refresh_snapshot = RefreshSnapshot(
            bid_ref=ui_state.get_selected_bid_ref(),
            page_uids=list(ui_state.selected_page_uids),
            active_page_uid=ui_state.active_page_uid,
            highlighted_condition_uids=set(ui_state.highlighted_condition_uids),
            project_uid=ui_state.selected_project_uid,
            database_selected=ui_state.is_database_selected(),
            selected_file_path=ui_state.selected_file_path,
            place_condition_uid=(
                ui_state.place_condition_uid if placement.is_active else None
            ),
            place_condition_uids=(
                list(ui_state.place_condition_uids) if placement.is_active else []
            ),
            selected_area_uid=selected_area_uid,
        )
        return True

    def finish_refresh(self, target: NavState) -> bool:
        if self._state != NavState.REFRESHING:
            self._refresh_snapshot = None
            logger.warning(
                "finish_refresh ignored because current state is %s",
                self._state.name,
            )
            return False
        self._refresh_snapshot = None
        if target not in _VALID_REFRESH_TARGETS:
            prev = self._state
            self._state = NavState.NO_FILE
            logger.error(
                "finish_refresh: transition %s -> %s failed, "
                "forced NO_FILE as recovery",
                prev.name,
                target.name,
            )
            return False
        self._state = target
        return True
