import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from ost_visualizer.domain.entities.bid import Bid
from ost_visualizer.domain.entities.identity_refs import BidRef
from ost_visualizer.domain.entities.page import Page
from ost_visualizer.domain.services.coordinate_transformation_service import (
    OSTCoordinateSystem,
)
from ost_visualizer.domain.services.page_scale_transform import (
    rescale_position_between_page_scales,
)
from ost_visualizer.presentation.components.page_combo import PageComboBox
from ost_visualizer.presentation.config import TAB_INDEX_TAKEOFF
from ost_visualizer.presentation.coordinators.ui_event_coordinator import (
    UIEventCoordinator,
)
from PySide6 import QtWidgets


class _RefreshSidebar:
    def __init__(self, page_combo: PageComboBox, refreshed_bid: Bid) -> None:
        self._page_combo = page_combo
        self._refreshed_bid = refreshed_bid
        self.clear_calls = 0

    def clear_sidebars(self) -> None:
        self.clear_calls += 1
        self._page_combo.clear()

    def load_bid_layers_sidebar(self) -> None:
        pass

    def load_conditions_sidebar(self) -> None:
        pass

    def update_conditions_quantities(self) -> None:
        pass
