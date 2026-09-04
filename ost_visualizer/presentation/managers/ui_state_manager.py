from dataclasses import dataclass
from typing import List, Optional, Set
from ...domain.entities.identity_refs import BidRef


@dataclass
class UIState:
    display_modes_synced: bool
    display_mode_3d: str
    display_mode_2d: str
    grayscale_enabled: bool


class UIStateManager:
    def __init__(self, config_model):
        self.config_model = config_model
        self.state = UIState(
            display_modes_synced=config_model.display_modes_synced,
            display_mode_3d=config_model.display_mode_3d,
            display_mode_2d=config_model.display_mode_2d,
            grayscale_enabled=config_model.grayscale_enabled,
        )
        self._selected_bid_ref: Optional[BidRef] = None
        self._selected_bid_refs: List[BidRef] = []
        self._selected_page_uids: List[str] = []
        self._database_file_path: Optional[str] = None
        self._selected_project_uid: Optional[str] = None
        self._selected_project_uids: List[str] = []
        self._selected_project_file_path: Optional[str] = None
        self._active_page_uid: Optional[str] = None
        self._place_condition_uid: Optional[str] = None
        self._place_condition_uids: List[str] = []
        self._highlighted_condition_uids: Set[str] = set()
        self._selected_area_uid: str = ""

    @property
    def selected_page_uids(self) -> List[str]:
        return self._selected_page_uids[:]

    @property
    def selected_file_path(self) -> Optional[str]:
        if self._selected_bid_ref:
            return self._selected_bid_ref.file_path
        return self._database_file_path

    @property
    def selected_project_uid(self) -> Optional[str]:
        return self._selected_project_uid

    @property
    def selected_project_uids(self) -> List[str]:
        return self._selected_project_uids[:]

    @property
    def selected_project_file_path(self) -> Optional[str]:
        return self._selected_project_file_path

    def get_selected_bid_ref(self) -> Optional[BidRef]:
        return self._selected_bid_ref

    def get_selected_bid_refs(self) -> List[BidRef]:
        return self._selected_bid_refs[:]

    @property
    def active_page_uid(self) -> Optional[str]:
        return self._active_page_uid

    @active_page_uid.setter
    def active_page_uid(self, value: Optional[str]) -> None:
        self._active_page_uid = value

    @property
    def place_condition_uid(self) -> Optional[str]:
        return self._place_condition_uid

    @place_condition_uid.setter
    def place_condition_uid(self, value: Optional[str]) -> None:
        self._place_condition_uid = value

    @property
    def place_condition_uids(self) -> List[str]:
        return self._place_condition_uids[:]

    def set_place_condition_uids(self, uids: List[str]) -> None:
        self._place_condition_uids = uids[:]

    @property
    def highlighted_condition_uids(self) -> Set[str]:
        return set(self._highlighted_condition_uids)

    def set_highlighted_conditions(self, uids: Set[str]) -> None:
        self._highlighted_condition_uids = set(uids)

    @property
    def selected_area_uid(self) -> str:
        return self._selected_area_uid

    @selected_area_uid.setter
    def selected_area_uid(self, value: str) -> None:
        self._selected_area_uid = value or ""

    def clear_place_condition(self) -> None:
        self._place_condition_uids = []
        self._place_condition_uid = None

    def sync_from_config(self) -> None:
        self.state.display_modes_synced = self.config_model.display_modes_synced
        self.state.display_mode_3d = self.config_model.display_mode_3d
        self.state.display_mode_2d = self.config_model.display_mode_2d
        self.state.grayscale_enabled = self.config_model.grayscale_enabled

    def reset_selections(self) -> None:
        self._selected_bid_ref = None
        self._selected_bid_refs = []
        self._selected_page_uids = []
        self._selected_project_uid = None
        self._selected_project_uids = []
        self._selected_project_file_path = None
        self._active_page_uid = None
        self._database_file_path = None
        self._highlighted_condition_uids = set()
        self._selected_area_uid = ""
        self.clear_place_condition()

    def set_page_selection(self, page_uids: List[str]) -> None:
        self._selected_page_uids = page_uids[:]

    def set_bid_selection(self, bid_ref: Optional[BidRef]) -> None:
        self._selected_bid_ref = bid_ref
        self._selected_bid_refs = [bid_ref] if bid_ref else []
        self._selected_project_uid = None
        self._selected_project_uids = []
        self._selected_project_file_path = None
        self._selected_page_uids = []
        self._active_page_uid = None
        self._highlighted_condition_uids = set()
        self._selected_area_uid = ""

    def set_bid_multi_selection(self, bid_refs: List[BidRef]) -> None:
        self._selected_bid_refs = list(bid_refs)

    def set_project_multi_selection(
        self, project_uids: List[str], file_path: Optional[str]
    ) -> None:
        self._selected_project_uids = list(project_uids)
        self._selected_project_file_path = file_path if project_uids else None

    def set_file_path(self, file_path: Optional[str]) -> None:
        if file_path and self._selected_bid_ref:
            self._selected_bid_ref = BidRef(
                file_path=file_path, bid_uid=self._selected_bid_ref.bid_uid
            )
        self._database_file_path = file_path

    def set_project_uid(self, project_uid: Optional[str]) -> None:
        self._selected_project_uid = project_uid
        self._selected_project_uids = [project_uid] if project_uid else []
        self._selected_project_file_path = (
            self._database_file_path if project_uid else None
        )

    def set_database_selected(
        self, selected: bool, file_path: Optional[str] = None
    ) -> None:
        if selected:
            self._selected_bid_ref = None
            self._selected_bid_refs = []
            self._selected_page_uids = []
            self._selected_project_uid = None
            self._selected_project_uids = []
            self._selected_project_file_path = None
        self._database_file_path = file_path

    def is_database_selected(self) -> bool:
        return self._selected_bid_ref is None and self._database_file_path is not None
