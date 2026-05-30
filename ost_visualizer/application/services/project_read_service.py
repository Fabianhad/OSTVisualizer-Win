import logging
from typing import Dict, List, Optional, Tuple
from ...domain.entities.area import BidArea
from ...domain.entities.cdn_type import CdnType
from ...domain.entities.cover_sheet import CoverSheetData, JobStatus
from ...domain.entities.employee import Employee, PayClass
from ...domain.entities.layer import BidLayer, merge_layers_for_bid
from ...domain.services.dimension_format_service import (
    display_to_inches as _display_to_inches,
)
from ...domain.services.dimension_format_service import (
    inches_to_display as _inches_to_display,
)
from ...domain.services.uom_service import (
    get_quantity_options_for_type as _get_quantity_options_for_type,
)
from ...domain.services.uom_service import get_uom_label as _get_uom_label
from ...domain.services.uom_service import (
    get_valid_uoms_for_calc_type as _get_valid_uoms_for_calc_type,
)


class ProjectReadService:
    def __init__(self, mdb_reader, logger: Optional[logging.Logger] = None):
        self._reader = mdb_reader
        self.logger = logger or logging.getLogger(__name__)

    def get_merged_bid_layers(self, file_path: str, bid_uid: str) -> List[BidLayer]:
        try:
            all_layers = self._reader.get_bid_layers_for_sidebar(file_path, bid_uid)
        except Exception:
            self.logger.warning("Failed to load bid layers", exc_info=True)
            return []
        return merge_layers_for_bid(all_layers)

    def get_cdn_types(self, file_path: str) -> Dict[str, CdnType]:
        try:
            return self._reader.get_cdn_types(file_path)
        except Exception:
            self.logger.warning("Failed to load CdnTypes", exc_info=True)
            return {}

    def get_job_statuses(self, file_path: str) -> List[JobStatus]:
        try:
            return self._reader.get_job_statuses(file_path)
        except Exception:
            self.logger.warning("Failed to load job statuses", exc_info=True)
            return []

    def is_bid_locked(self, file_path: str, bid_status: Optional[str]) -> bool:
        if not bid_status:
            return False
        for s in self.get_job_statuses(file_path):
            if s.name == bid_status:
                return s.locked
        return False

    def get_cover_sheet_data(
        self, file_path: str, bid_uid: str
    ) -> Optional[CoverSheetData]:
        try:
            return self._reader.get_cover_sheet_data(file_path, bid_uid)
        except Exception:
            self.logger.warning("Failed to load cover sheet data", exc_info=True)
            return None

    def get_estimator_uids_in_use(self, file_path: str) -> set:
        try:
            return self._reader.get_estimator_uids_in_use(file_path)
        except Exception:
            self.logger.warning("Failed to load estimator UIDs", exc_info=True)
            return set()

    def get_condition_type_uids_in_use(self, file_path: str) -> set:
        try:
            return self._reader.get_condition_type_uids_in_use(file_path)
        except Exception:
            self.logger.warning("Failed to load condition type UIDs", exc_info=True)
            return set()

    def get_layer_uids_in_use(self, file_path: str, bid_uid: str) -> set:
        try:
            return self._reader.get_layer_uids_in_use(file_path, bid_uid)
        except Exception:
            self.logger.warning("Failed to load layer UIDs in use", exc_info=True)
            return set()

    def get_employees_and_pay_classes(
        self, file_path: str
    ) -> Tuple[List[Employee], List[PayClass]]:
        try:
            return self._reader.get_employees_and_pay_classes(file_path)
        except Exception:
            self.logger.warning("Failed to load employees", exc_info=True)
            return [], []

    def get_bid_areas(self, file_path: str, bid_uid: str) -> List[BidArea]:
        try:
            return self._reader.get_bid_areas(file_path, bid_uid)
        except Exception:
            self.logger.warning("Failed to load bid areas", exc_info=True)
            return []

    def get_settings_defaults(self, file_path: str) -> dict:
        try:
            return self._reader.get_settings_defaults(file_path)
        except Exception:
            self.logger.warning("Failed to load settings defaults", exc_info=True)
            return {}

    def get_pages_with_takeoffs(self, file_path: str, bid_uid: str) -> set:
        try:
            return self._reader.get_pages_with_takeoffs(file_path, bid_uid)
        except Exception:
            self.logger.warning("Failed to load pages with takeoffs", exc_info=True)
            return set()

    def get_pages_with_delete_content(self, file_path: str, bid_uid: str) -> set:
        try:
            return self._reader.get_pages_with_delete_content(file_path, bid_uid)
        except Exception:
            self.logger.warning(
                "Failed to load pages with delete-sensitive content", exc_info=True
            )
            return set()

    @staticmethod
    def get_uom_label(uom_code: int) -> str:
        return _get_uom_label(uom_code)

    @staticmethod
    def get_quantity_options_for_type(condition_type: int) -> list:
        return _get_quantity_options_for_type(condition_type)

    @staticmethod
    def get_valid_uoms_for_calc_type(calc_type: int, metric: bool = False) -> list:
        return _get_valid_uoms_for_calc_type(calc_type, metric)

    @staticmethod
    def display_to_inches(text: str, metric: bool = False) -> Optional[float]:
        return _display_to_inches(text, metric)

    @staticmethod
    def inches_to_display(inches: float, metric: bool = False) -> str:
        return _inches_to_display(inches, metric)
