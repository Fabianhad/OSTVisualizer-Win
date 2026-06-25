import logging
from typing import Optional
from ....domain.aggregates.ost_aggregate import OstAggregate
from ....domain.entities.identity_refs import BidRef
from ....domain.entities.layer import normalize_layer_name
from ....domain.entities.page import build_pages_from_bid_data
from ....domain.entities.project_factory import build_bid
from ....domain.services.file_manager_service import FileManager


class LoadBidUseCase:
    def __init__(
        self,
        model: OstAggregate,
        file_manager: FileManager,
        logger: Optional[logging.Logger] = None,
    ):
        self.model = model
        self.file_manager = file_manager
        self.logger = logger or logging.getLogger(__name__)

    def execute(self, bid_ref: BidRef) -> bool:
        if not bid_ref.bid_uid:
            self.logger.warning("Cannot load bid: empty bid UID")
            return False
        bid_data = self.file_manager.load_bid(bid_ref.bid_uid, bid_ref.file_path)
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
        self.model.set_pages(pages)
        self.model.set_annotations(bid_data.bid_annotations)
        self.model.last_selected_page_uid = bid_data.selected_page_uid
        self.model.deselect_pages()
        return True
