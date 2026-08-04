import logging
from dataclasses import dataclass
from typing import Optional
from ...dtos.user_workspace_state_dtos import UserBidWorkspaceState
from ....domain.aggregates.ost_aggregate import OstAggregate
from ....domain.entities.identity_refs import BidRef
from ....domain.entities.layer import normalize_layer_name
from ....domain.entities.page import build_pages_from_bid_data
from ....domain.entities.project_factory import build_bid
from ....domain.entities.file_results import BidLoadResult
from ....domain.services.file_manager_service import FileManager


@dataclass(frozen=True)
class PreparedBidLoad:
    bid_data: BidLoadResult
    sql_workspace_state: Optional[UserBidWorkspaceState]


class LoadBidUseCase:
    def __init__(
        self,
        model: OstAggregate,
        project_data_service,
        file_manager: FileManager,
        concurrency_tokens,
        sql_workspace_state_service,
        logger: Optional[logging.Logger] = None,
    ):
        self.model = model
        self._project_data = project_data_service
        self.file_manager = file_manager
        self.logger = logger or logging.getLogger(__name__)
        self._concurrency_tokens = concurrency_tokens
        self._sql_workspace = sql_workspace_state_service

    def execute(self, bid_ref: BidRef) -> bool:
        if not bid_ref.bid_uid:
            self.logger.warning("Cannot load bid: empty bid UID")
            return False
        if self._sql_workspace.uses_sql_workspace(bid_ref.file_path):
            raise RuntimeError(
                "SQL bid loads must run through the background navigation service"
            )
        bid_data = self.prepare(bid_ref)
        return self.apply_prepared(bid_ref, bid_data)

    def prepare(self, bid_ref: BidRef) -> PreparedBidLoad:
        self._concurrency_tokens.load_bid(bid_ref.file_path, bid_ref.bid_uid)
        bid_data = self.file_manager.prepare_bid_load(
            bid_ref.bid_uid, bid_ref.file_path
        )
        workspace_state = None
        if self._sql_workspace.uses_sql_workspace(bid_ref.file_path):
            workspace_state = self._sql_workspace.load_bid_state(
                bid_ref.file_path, bid_ref.bid_uid
            )
        return PreparedBidLoad(bid_data, workspace_state)

    def apply_prepared(self, bid_ref: BidRef, prepared: PreparedBidLoad) -> bool:
        bid_data = prepared.bid_data
        self.file_manager.apply_bid_load(bid_ref.file_path)
        self.model.bid_conditions = bid_data.bid_conditions
        self.model.bid_takeoffs = bid_data.bid_takeoffs
        self.model.bid_areas = dict(bid_data.bid_areas or {})
        self.model.bid_takeoff_extras = bid_data.takeoff_extras
        self.model.bid_condition_folders = bid_data.bid_condition_folders
        self.model.page_area_selections = bid_data.page_area_selections
        self.model.bid_layers = list(bid_data.bid_layers or [])
        self.model.bid_layer_visibility = {}
        self.model.bid_layer_names_by_uid = {}
        self.model.bid_layer_visibility_by_name = {}
        for layer in self.model.bid_layers:
            if not layer.uid:
                continue
            layer_uid = str(layer.uid)
            layer_name = normalize_layer_name(layer.name)
            visible = bool(layer.show)
            self.model.bid_layer_visibility[layer_uid] = visible
            if layer_name:
                self.model.bid_layer_names_by_uid[layer_uid] = layer_name
                self.model.bid_layer_visibility_by_name[layer_name] = visible
        self.model.current_bid_ref = bid_ref
        bid_info = self.model.find_bid_info(bid_ref)
        self.model.current_bid = build_bid(bid_info) if bid_info else None
        pages = bid_data.pages
        if not pages:
            pages = build_pages_from_bid_data(
                bid_data.bid_pages, self.model.bid_takeoffs
            )
        selected_page_uid = bid_data.selected_page_uid
        if prepared.sql_workspace_state is not None:
            pages_by_uid = {str(page.uid): page for page in pages.values()}
            for page in pages_by_uid.values():
                page.zoom_fac = 0.0
                page.current_x = 0.0
                page.current_y = 0.0
            selected_page_uid = prepared.sql_workspace_state.active_page_uid
            if selected_page_uid not in pages_by_uid:
                selected_page_uid = None
            for page_uid, view_state in prepared.sql_workspace_state.page_views.items():
                page = pages_by_uid.get(page_uid)
                if page is None:
                    continue
                page.zoom_fac = view_state.zoom_fac
                page.current_x = view_state.current_x
                page.current_y = view_state.current_y
        self.model.set_pages(pages)
        self.model.set_annotations(bid_data.bid_annotations)
        if bid_data.cover_sheet_data is not None:
            self._project_data.replace_cover_sheet_data(
                bid_ref.file_path,
                bid_ref.bid_uid,
                bid_data.cover_sheet_data,
            )
        if bid_data.page_delete_content_uids is not None:
            self._project_data.replace_page_delete_content_uids(
                bid_ref.file_path,
                bid_ref.bid_uid,
                bid_data.page_delete_content_uids,
            )
        self.model.last_selected_page_uid = selected_page_uid
        self.model.deselect_pages()
        return True
