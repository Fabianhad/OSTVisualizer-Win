import os
import unittest
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from ost_visualizer.domain.entities.identity_refs import BidRef
from ost_visualizer.domain.entities.page import Page
from ost_visualizer.presentation.components.page_combo import PageComboBox
from ost_visualizer.presentation.coordinators.ui_event_coordinator import (
    UIEventCoordinator,
)
from PySide6 import QtWidgets


class _SidebarProjection:
    def __init__(self, page_combo):
        self._page_combo = page_combo
        # Stale display state that only a quantity projection can replace.
        self.rows = {"condition-1": {"uom": "EA", "quantity": 1.0}}
        self.quantity_refreshes = 0
        self.calls = []

    def load_takeoff_sidebar_from_memory(self, *_args):
        raise AssertionError("MDB refresh must not use the SQL memory path")

    def load_takeoff_sidebar(self, bid_ref, bid_data_cache):
        self._page_combo.load_bid(bid_data_cache[bid_ref])

    def load_bid_layers_sidebar(self):
        pass

    def load_conditions_sidebar(self):
        # Rebuilding condition rows intentionally starts with empty display cells;
        # the authoritative quantity projection must run after the rebuild.
        self.calls.append("load_conditions_sidebar")
        self.rows = {"condition-1": {"uom": "", "quantity": None}}

    def update_conditions_quantities(self):
        self.calls.append("update_conditions_quantities")
        self.quantity_refreshes += 1
        self.rows = {"condition-1": {"uom": "EA", "quantity": 5.0}}

    def load_condition_summary(self):
        pass


class PageNavigationQuantityProjectionTests(unittest.TestCase):
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
        active_page_events = []
        page_combo.active_page_changed.connect(active_page_events.append)
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
        coordinator._toolbar = SimpleNamespace(refresh=lambda: None)
        coordinator._nav = SimpleNamespace(is_refreshing=False)
        coordinator.conditions_sidebar = None
        coordinator._selection_projected_condition_uids = set()
        coordinator.main_window = SimpleNamespace(
            notify_takeoff_workspace_activated=lambda: None
        )
        coordinator._sync_embedded_renderer_exposure = lambda: None
        coordinator._sync_page_info_status = lambda: None
        # The page is unchanged, so the page handler must not be what refreshes the
        # quantities: record it separately from the sidebar projection.
        handled_pages = []
        coordinator.handle_active_page_changed = handled_pages.append
        try:
            coordinator._activate_takeoff_workspace()
        finally:
            page_combo.deleteLater()
        self.assertEqual(
            projection.rows,
            {"condition-1": {"uom": "EA", "quantity": 5.0}},
        )
        # The projection ran after the condition rows were rebuilt, once.
        self.assertEqual(
            projection.calls,
            ["load_conditions_sidebar", "update_conditions_quantities"],
        )
        self.assertEqual(handled_pages, ["page-1"])
        self.assertEqual(active_page_events, [])

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
        coordinator._toolbar = SimpleNamespace(refresh=lambda: None)
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
        # Rows were rebuilt first and the final display state is a projection.
        self.assertEqual(projection.calls[0], "load_conditions_sidebar")
        self.assertEqual(projection.calls[-1], "update_conditions_quantities")
        self.assertEqual(projection.calls.count("load_conditions_sidebar"), 1)
