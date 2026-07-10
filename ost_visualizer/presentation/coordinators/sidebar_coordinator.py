import logging
from typing import Dict, Mapping
from ...application.dtos.condition_summary_dtos import ConditionSummaryGrouping
from ...application.use_cases.project.condition_summary_service import (
    ConditionSummaryService,
)
from ...domain.entities.bid import Bid
from ...domain.entities.identity_refs import BidRef

logger = logging.getLogger(__name__)


class SidebarCoordinator:
    def __init__(self, project_read_service, ui_state_manager, project_data):
        self._project_read_service = project_read_service
        self._ui_state = ui_state_manager
        self._project_data = project_data
        self.takeoff_sidebar = None
        self.conditions_sidebar = None
        self.condition_summary_tab = None
        self.bid_layers_sidebar = None
        self._view_stack = None
        self._condition_summary_service = ConditionSummaryService()

    def set_view_stack(self, view_stack) -> None:
        self._view_stack = view_stack

    def load_takeoff_sidebar(
        self, bid_ref: BidRef, bid_data_cache: Dict[BidRef, Bid]
    ) -> None:
        if not self.takeoff_sidebar:
            return
        bid = bid_data_cache.get(bid_ref)
        if not bid:
            self.takeoff_sidebar.clear()
            return
        pages_with_takeoffs = self._project_read_service.get_pages_with_takeoffs(
            bid_ref.file_path, bid_ref.bid_uid
        )
        self.takeoff_sidebar.load_bid(bid, pages_with_takeoffs=pages_with_takeoffs)

    def load_conditions_sidebar(self) -> None:
        if not self.conditions_sidebar:
            return
        bid_ref = self._ui_state.get_selected_bid_ref()
        if not bid_ref:
            self.conditions_sidebar.clear()
            return
        conditions = self._project_data.get_bid_conditions()
        folders = self._project_data.get_bid_condition_folders()
        bid = self._project_data.get_bid(bid_ref)
        project_name = (bid.name or "") if bid else ""
        grayscale = self._ui_state.state.grayscale_enabled
        layers = self._project_read_service.get_merged_bid_layers(
            bid_ref.file_path, bid_ref.bid_uid
        )
        self._project_data.set_bid_layer_visibility(layers)
        condition_types = self._project_read_service.get_cdn_types(
            bid_ref.file_path
        ).values()
        self.conditions_sidebar.set_available_layers(layers)
        self.conditions_sidebar.set_available_condition_types(list(condition_types))
        self.conditions_sidebar.load_conditions(
            conditions, folders, project_name, grayscale
        )
        self._sync_sidebar_highlight_from_ui_state(conditions)

    def _sync_sidebar_highlight_from_ui_state(
        self, conditions: Mapping[str, object]
    ) -> None:
        if not self.conditions_sidebar:
            return
        current_highlight = set(self._ui_state.highlighted_condition_uids)
        valid_highlight = current_highlight.intersection(conditions)
        if valid_highlight != current_highlight:
            self._ui_state.set_highlighted_conditions(valid_highlight)
        if valid_highlight or self.conditions_sidebar.get_selected_condition_uids():
            self.conditions_sidebar.highlight_conditions(valid_highlight, reveal=False)

    def load_condition_summary(
        self, grouping: ConditionSummaryGrouping | None = None
    ) -> None:
        if not self.condition_summary_tab:
            return
        bid_ref = self._ui_state.get_selected_bid_ref()
        if not bid_ref:
            self.condition_summary_tab.clear()
            return
        grouping = grouping or self.condition_summary_tab.grouping
        conditions = self._project_data.get_bid_conditions()
        folders = self._project_data.get_bid_condition_folders()
        bid = self._project_data.get_bid(bid_ref)
        project_name = (bid.name or "") if bid else ""
        metric = bool(bid.measure_base) if bid else False
        areas = self._project_read_service.get_bid_areas(
            bid_ref.file_path, bid_ref.bid_uid
        )
        root = self._condition_summary_service.build_summary(
            conditions=conditions,
            folders=folders,
            takeoffs=self._project_data.get_all_takeoffs(),
            pages=self._project_data.get_all_pages(),
            areas=areas,
            project_name=project_name,
            grouping=grouping,
            metric=metric,
        )
        self.condition_summary_tab.load_summary(
            root, grouping, self._ui_state.state.grayscale_enabled
        )

    def set_condition_summary_grouping(
        self, grouping: ConditionSummaryGrouping
    ) -> None:
        self.load_condition_summary(grouping)

    def load_bid_layers_sidebar(self) -> None:
        if not self.bid_layers_sidebar:
            return
        bid_ref = self._ui_state.get_selected_bid_ref()
        if not bid_ref:
            self.bid_layers_sidebar.clear()
            return
        merged = self._project_read_service.get_merged_bid_layers(
            bid_ref.file_path, bid_ref.bid_uid
        )
        self._project_data.set_bid_layer_visibility(merged)
        if not merged:
            self.bid_layers_sidebar.clear()
            return
        used_uids = self._project_read_service.get_layer_uids_in_use(
            bid_ref.file_path, bid_ref.bid_uid
        )
        self.bid_layers_sidebar.load_layers(merged, used_uids=used_uids)

    def clear_sidebars(self) -> None:
        if self.takeoff_sidebar:
            self.takeoff_sidebar.clear()
        if self.conditions_sidebar:
            self.conditions_sidebar.clear()
        if self.condition_summary_tab:
            self.condition_summary_tab.clear()
        if self.bid_layers_sidebar:
            self.bid_layers_sidebar.clear()

    def refresh_conditions_ui(self) -> None:
        self.load_conditions_sidebar()
        self.update_conditions_quantities()
        self.load_condition_summary()

    def update_conditions_quantities(self, condition_uids=None) -> None:
        if not self.conditions_sidebar:
            return
        is_partial = condition_uids is not None
        affected_condition_uids = set()
        if condition_uids is not None:
            affected_condition_uids = {str(uid) for uid in condition_uids if uid}
            if not affected_condition_uids:
                return
        is_3d = self._view_stack and self._view_stack.currentIndex() == 0
        if is_3d:
            page_uids = self._project_data.get_selected_page_uids()
        else:
            active_2d = self._ui_state.active_page_uid
            page_uids = [active_2d] if active_2d else []
        if not page_uids:
            self.conditions_sidebar.update_quantities({}, partial=is_partial)
            return
        if is_partial:
            quantities = self._project_data.compute_quantities_for_pages(
                page_uids, only_condition_uids=affected_condition_uids
            )
            self.conditions_sidebar.update_quantities(quantities, partial=True)
            return
        quantities = self._project_data.compute_quantities_for_pages(page_uids)
        self.conditions_sidebar.update_quantities(quantities)

    def cleanup(self) -> None:
        self.takeoff_sidebar = None
        self.conditions_sidebar = None
        self.condition_summary_tab = None
        self.bid_layers_sidebar = None
        self._view_stack = None
        self._condition_summary_service = None
        self._project_read_service = None
        self._ui_state = None
        self._project_data = None
