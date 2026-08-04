import os
import unittest
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6 import QtWidgets
from ost_visualizer.domain.entities.condition import Condition
from ost_visualizer.domain.entities.identity_refs import BidRef
from ost_visualizer.domain.entities.page import Page
from ost_visualizer.domain.entities.takeoff import Takeoff
from ost_visualizer.domain.services.condition_quantity_service import (
    compute_page_quantities,
)
from ost_visualizer.domain.services.uom_service import CALC_COUNT, UOM_EACH
from ost_visualizer.presentation.components.conditions_sidebar import ConditionsSidebar
from ost_visualizer.presentation.components.page_combo import PageComboBox
from ost_visualizer.presentation.coordinators.ui_event_coordinator import (
    UIEventCoordinator,
)


class _SidebarProjection:
    def __init__(self, page_combo):
        self._page_combo = page_combo
        self.rows = {"condition-1": {"uom": "EA", "quantity": 5.0}}
        self.quantity_refreshes = 0

    def load_takeoff_sidebar_from_memory(self, *_args):
        raise AssertionError("MDB refresh must not use the SQL memory path")

    def load_takeoff_sidebar(self, bid_ref, bid_data_cache):
        self._page_combo.load_bid(bid_data_cache[bid_ref])

    def load_bid_layers_sidebar(self):
        pass

    def load_conditions_sidebar(self):
        # Rebuilding condition rows intentionally starts with empty display cells;
        # the authoritative quantity projection must run after the rebuild.
        self.rows = {"condition-1": {"uom": "", "quantity": None}}

    def update_conditions_quantities(self):
        self.quantity_refreshes += 1
        self.rows = {"condition-1": {"uom": "EA", "quantity": 5.0}}

    def load_condition_summary(self):
        pass


class CoverSheetSidebarRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def test_same_bid_refresh_rebuilds_condition_quantities_when_page_is_unchanged(
        self,
    ):
        bid_ref = BidRef("cover-sheet.mdb", "7")
        pages = [
            Page(uid="page-1", name="A101", sequence=1),
            Page(uid="page-2", name="A102", sequence=2),
        ]
        deleted_page = Page(uid="page-3", name="A103", sequence=3)
        initial_bid = SimpleNamespace(
            uid="7", folders={}, pages_without_folder=[*pages, deleted_page]
        )
        refreshed_bid = SimpleNamespace(uid="7", folders={}, pages_without_folder=pages)
        page_combo = PageComboBox()
        page_combo.load_bid(initial_bid)
        page_combo.restore_selection(["page-1"], "page-1")
        projection = _SidebarProjection(page_combo)
        page_combo.active_page_changed.connect(
            lambda _page_uid: projection.update_conditions_quantities()
        )
        coordinator = UIEventCoordinator.__new__(UIEventCoordinator)
        coordinator.ui_state_manager = SimpleNamespace(
            get_selected_bid_ref=lambda: bid_ref,
            selected_page_uids=["page-1"],
            active_page_uid="page-1",
            highlighted_condition_uids=set(),
            set_highlighted_conditions=lambda _uids: None,
        )
        coordinator.project_data = SimpleNamespace(
            get_page=lambda uid: next(
                (page for page in pages if page.uid == uid), None
            ),
            get_last_selected_page_uid=lambda: "page-1",
            get_bid_conditions=lambda: {},
        )
        coordinator.takeoff_sidebar = page_combo
        coordinator._sidebar = projection
        coordinator._bid_data_cache = {bid_ref: refreshed_bid}
        coordinator._project_write_service = SimpleNamespace(
            uses_sql_collaboration_mutations=lambda _database_id: False
        )
        coordinator._page_settings_bar = None
        coordinator._takeoff_workspace_bid_ref = None
        coordinator._pending_takeoff_page_uids = ["page-1"]
        coordinator._pending_takeoff_active_page_uid = "page-1"
        coordinator._pending_takeoff_selected_area_uid = ""
        coordinator._pending_takeoff_place_condition_uid = None
        coordinator._pending_takeoff_place_condition_uids = []
        coordinator._placement = SimpleNamespace()
        coordinator._nav = SimpleNamespace(is_refreshing=False)
        coordinator.conditions_sidebar = None
        coordinator._selection_projected_condition_uids = set()
        coordinator.main_window = SimpleNamespace(
            notify_takeoff_workspace_activated=lambda: None
        )
        coordinator._sync_embedded_renderer_exposure = lambda: None
        coordinator._sync_page_info_status = lambda: None
        coordinator.handle_active_page_changed = (
            lambda _page_uid: projection.update_conditions_quantities()
        )
        try:
            coordinator._activate_takeoff_workspace()
        finally:
            page_combo.deleteLater()
        self.assertEqual(
            projection.rows,
            {"condition-1": {"uom": "EA", "quantity": 5.0}},
        )
        self.assertGreaterEqual(projection.quantity_refreshes, 1)

    def test_zero_remaining_quantity_keeps_the_condition_uom_visible(self):
        sidebar = ConditionsSidebar(
            None, uom_label_fn=lambda code: {7: "EA"}.get(code, "")
        )
        condition = Condition(uid="condition-1", name="Concrete", uom1=7)
        try:
            sidebar.load_conditions(
                {condition.uid: condition}, {}, "Bid", grayscale=False
            )
            sidebar.update_quantities({})
            item = sidebar._condition_items[condition.uid]
            self.assertEqual(item.text(2), "0 EA")
        finally:
            sidebar.deleteLater()

    def test_current_page_deletion_activates_a_remaining_page_and_projects_uoms(self):
        bid_ref = BidRef("cover-sheet.mdb", "7")
        original_pages = [
            Page(uid="page-1", name="A101", sequence=1),
            Page(uid="page-2", name="A102", sequence=2),
            Page(uid="page-3", name="A103", sequence=3),
        ]
        remaining_pages = [original_pages[0], original_pages[2]]
        original_bid = SimpleNamespace(
            uid="7", folders={}, pages_without_folder=original_pages
        )
        refreshed_bid = SimpleNamespace(
            uid="7", folders={}, pages_without_folder=remaining_pages
        )
        page_combo = PageComboBox()
        page_combo.load_bid(original_bid)
        page_combo.restore_selection(["page-2"], "page-2")
        projection = _SidebarProjection(page_combo)
        page_combo.active_page_changed.connect(
            lambda _page_uid: projection.update_conditions_quantities()
        )
        coordinator = UIEventCoordinator.__new__(UIEventCoordinator)
        coordinator.ui_state_manager = SimpleNamespace(
            get_selected_bid_ref=lambda: bid_ref,
            selected_page_uids=["page-2"],
            active_page_uid="page-2",
            highlighted_condition_uids=set(),
            set_highlighted_conditions=lambda _uids: None,
        )
        coordinator.project_data = SimpleNamespace(
            get_page=lambda uid: next(
                (page for page in remaining_pages if page.uid == uid), None
            ),
            get_last_selected_page_uid=lambda: "page-2",
            get_bid_conditions=lambda: {},
        )
        coordinator.takeoff_sidebar = page_combo
        coordinator._sidebar = projection
        coordinator._bid_data_cache = {bid_ref: refreshed_bid}
        coordinator._project_write_service = SimpleNamespace(
            uses_sql_collaboration_mutations=lambda _database_id: False
        )
        coordinator._page_settings_bar = None
        coordinator._takeoff_workspace_bid_ref = None
        coordinator._pending_takeoff_page_uids = None
        coordinator._pending_takeoff_active_page_uid = None
        coordinator._pending_takeoff_selected_area_uid = ""
        coordinator._pending_takeoff_place_condition_uid = None
        coordinator._pending_takeoff_place_condition_uids = []
        coordinator._placement = SimpleNamespace()
        coordinator._nav = SimpleNamespace(is_refreshing=False)
        coordinator.conditions_sidebar = None
        coordinator._selection_projected_condition_uids = set()
        coordinator.main_window = SimpleNamespace(
            notify_takeoff_workspace_activated=lambda: None
        )
        coordinator._sync_embedded_renderer_exposure = lambda: None
        coordinator._sync_page_info_status = lambda: None
        coordinator.handle_active_page_changed = (
            lambda _page_uid: projection.update_conditions_quantities()
        )
        try:
            coordinator._activate_takeoff_workspace()
        finally:
            page_combo.deleteLater()
        self.assertEqual(page_combo.get_active_page_uid(), "page-1")
        self.assertEqual(
            projection.rows,
            {"condition-1": {"uom": "EA", "quantity": 5.0}},
        )

    def test_conditions_spanning_deleted_and_remaining_pages_recalculate(self):
        spanning = Condition(
            uid="spanning",
            name="Spanning",
            condition_type=Condition.TYPE_COUNT,
            uom1=UOM_EACH,
            calc_type1=CALC_COUNT,
        )
        deleted_only = Condition(
            uid="deleted-only",
            name="Deleted only",
            condition_type=Condition.TYPE_COUNT,
            uom1=UOM_EACH,
            calc_type1=CALC_COUNT,
        )
        conditions = {spanning.uid: spanning, deleted_only.uid: deleted_only}
        takeoffs = [
            Takeoff(uid="takeoff-1", condition_uid=spanning.uid, page_uid="page-1"),
            Takeoff(uid="takeoff-2", condition_uid=spanning.uid, page_uid="page-2"),
            Takeoff(
                uid="takeoff-3",
                condition_uid=deleted_only.uid,
                page_uid="page-1",
            ),
        ]
        remaining_takeoffs = [
            takeoff for takeoff in takeoffs if takeoff.page_uid == "page-2"
        ]
        quantities = compute_page_quantities(conditions, remaining_takeoffs)
        sidebar = ConditionsSidebar(
            None,
            uom_label_fn=lambda code: "EA" if code == UOM_EACH else "",
        )
        try:
            sidebar.load_conditions(conditions, {}, "Bid", grayscale=False)
            sidebar.update_quantities(quantities)
            self.assertEqual(sidebar._condition_items[spanning.uid].text(2), "1 EA")
            self.assertEqual(sidebar._condition_items[deleted_only.uid].text(2), "0 EA")
        finally:
            sidebar.deleteLater()


if __name__ == "__main__":
    unittest.main()
