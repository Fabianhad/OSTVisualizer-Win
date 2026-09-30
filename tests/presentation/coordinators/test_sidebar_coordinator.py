from PySide6 import QtCore, QtGui, QtWidgets
from ost_visualizer.presentation.coordinators.sidebar_coordinator import (
    SidebarCoordinator,
)
from ost_visualizer.presentation.components.page_combo import PageComboBox
from ost_visualizer.presentation.components.conditions_sidebar import ConditionsSidebar
from ost_visualizer.domain.entities.page import Page
from ost_visualizer.domain.entities.identity_refs import BidRef
from ost_visualizer.domain.entities.condition import Condition
from ost_visualizer.domain.entities.bid import Bid
from types import SimpleNamespace
import unittest
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6 import QtCore, QtWidgets

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def _app():
    app = QtWidgets.QApplication.instance()
    if app is None:
        app = QtWidgets.QApplication([])
    return app


class SidebarCoordinatorConditionBehaviorTests(unittest.TestCase):
    def _make_conditions(self, count: int, prefix: str = "c"):
        return {
            f"{prefix}{index}": Condition(
                uid=f"{prefix}{index}",
                name=f"Condition {index}",
                ref_no=index,
            )
            for index in range(1, count + 1)
        }

    def _make_sidebar_coordinator(self, conditions, highlighted=()):
        sidebar = ConditionsSidebar(None)
        self.addCleanup(sidebar.close)

        class UiState:
            def __init__(self, highlighted_uids):
                self.highlighted_condition_uids = set(highlighted_uids)
                self.state = SimpleNamespace(grayscale_enabled=False)
                self._bid_ref = BidRef("db.mdb", "bid-1")

            def get_selected_bid_ref(self):
                return self._bid_ref

            def set_highlighted_conditions(self, uids):
                self.highlighted_condition_uids = set(uids)

        ui_state = UiState(highlighted)
        project_data = SimpleNamespace(
            get_bid_conditions=lambda: conditions,
            get_bid_condition_folders=lambda: {},
            get_bid=lambda _bid_ref: SimpleNamespace(name="Project"),
            set_bid_layer_visibility=lambda _layers: None,
        )
        read_service = SimpleNamespace(
            get_merged_bid_layers=lambda _file_path, _bid_uid: [],
            get_cdn_types=lambda _file_path: {},
        )
        coordinator = SidebarCoordinator(read_service, ui_state, project_data)
        coordinator.conditions_sidebar = sidebar
        return coordinator, sidebar, ui_state

    def test_layer_coordinator_keeps_empty_loaded_bid_distinct_from_no_bid(self):
        calls = []
        bid_ref = BidRef("db.mdb", "bid-1")
        ui_state = SimpleNamespace(get_selected_bid_ref=lambda: bid_ref)
        project_data = SimpleNamespace(
            get_bid_layer_snapshot=lambda: [],
            get_layer_uids_in_use=lambda: set(),
            set_bid_layer_visibility=lambda _layers: None,
        )
        read_service = SimpleNamespace(
            get_merged_bid_layers=lambda _path, _bid_uid: [],
            get_layer_uids_in_use=lambda _path, _bid_uid: set(),
        )
        coordinator = SidebarCoordinator(read_service, ui_state, project_data)
        coordinator.bid_layers_sidebar = SimpleNamespace(
            clear=lambda: calls.append(("clear",)),
            load_layers=lambda layers, used_uids: calls.append(
                ("load", list(layers), set(used_uids))
            ),
        )
        coordinator.load_bid_layers_sidebar()
        coordinator.load_bid_layers_sidebar_from_memory()
        self.assertEqual(calls, [("load", [], set()), ("load", [], set())])

    def test_memory_page_refresh_rebuilds_picker_from_authoritative_pages(self):
        bid_ref = BidRef("db.mdb", "bid-1")
        stale_page = Page(uid="old-page", name="Old page", sequence=1)
        current_page = Page(uid="new-page", name="New page", sequence=2)
        cached_bid = Bid(
            uid=bid_ref.bid_uid,
            name="Bid",
            page_count=1,
            pages_without_folder=[stale_page],
        )
        page_combo = PageComboBox()
        self.addCleanup(page_combo.close)
        coordinator = SidebarCoordinator(
            SimpleNamespace(),
            SimpleNamespace(get_selected_bid_ref=lambda: bid_ref),
            SimpleNamespace(get_all_pages=lambda: [current_page]),
        )
        coordinator.takeoff_sidebar = page_combo
        coordinator.load_takeoff_sidebar_from_memory(
            bid_ref,
            {bid_ref: cached_bid},
        )
        self.assertEqual(set(page_combo._page_items), {current_page.uid})
        self.assertEqual(cached_bid.pages_without_folder, [current_page])

    def test_sidebar_coordinator_load_applies_internal_highlight_by_uid(self):
        conditions = {
            "c1": Condition(uid="c1", name="Duplicate Name", ref_no=1),
            "c2": Condition(uid="c2", name="Duplicate Name", ref_no=2),
        }
        coordinator, sidebar, ui_state = self._make_sidebar_coordinator(
            conditions, highlighted={"c2"}
        )
        coordinator.load_conditions_sidebar()
        self.assertEqual(ui_state.highlighted_condition_uids, {"c2"})
        self.assertEqual(sidebar.get_selected_condition_uids(), ["c2"])
        self.assertFalse(sidebar._condition_items["c1"].isSelected())
        self.assertTrue(sidebar._condition_items["c2"].isSelected())

    def test_sidebar_coordinator_load_clears_stale_visual_highlight(self):
        conditions = self._make_conditions(2)
        coordinator, sidebar, ui_state = self._make_sidebar_coordinator(
            conditions, highlighted={"c1"}
        )
        coordinator.load_conditions_sidebar()
        self.assertEqual(sidebar.get_selected_condition_uids(), ["c1"])
        ui_state.set_highlighted_conditions(set())
        coordinator.load_conditions_sidebar()
        self.assertEqual(ui_state.highlighted_condition_uids, set())
        self.assertEqual(sidebar.get_selected_condition_uids(), [])

    def test_sidebar_coordinator_load_drops_missing_internal_highlight(self):
        coordinator, sidebar, ui_state = self._make_sidebar_coordinator(
            self._make_conditions(1), highlighted={"missing"}
        )
        coordinator.load_conditions_sidebar()
        self.assertEqual(ui_state.highlighted_condition_uids, set())
        self.assertEqual(sidebar.get_selected_condition_uids(), [])

    def test_sidebar_coordinator_load_sync_does_not_emit_condition_selected(self):
        coordinator, sidebar, _ui_state = self._make_sidebar_coordinator(
            self._make_conditions(1), highlighted={"c1"}
        )
        emitted = []
        sidebar.condition_selected.connect(emitted.append)
        coordinator.load_conditions_sidebar()
        self.assertEqual(sidebar.get_selected_condition_uids(), ["c1"])
        self.assertEqual(emitted, [])

    @classmethod
    def setUpClass(cls):
        cls.app = _app()
        cls._quit_on_last_window_closed = cls.app.quitOnLastWindowClosed()
        cls.app.setQuitOnLastWindowClosed(False)

    @classmethod
    def tearDownClass(cls):
        cls.app.setQuitOnLastWindowClosed(cls._quit_on_last_window_closed)

    def tearDown(self):
        self.app.processEvents()


class SidebarQuantityProjectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def test_sidebar_quantities_include_hidden_layer_conditions(self):
        quantity_payloads = []
        visible = Condition(uid="c1", name="Visible", layer_uid="l1")
        hidden = Condition(uid="c2", name="Hidden", layer_uid="l2")
        hidden.layer_visible = False
        project_data = SimpleNamespace(
            get_selected_page_uids=lambda: ["p1"],
            get_bid_conditions=lambda: {"c1": visible, "c2": hidden},
            compute_quantities_for_pages=lambda page_uids: {
                "c1": (1.0, 0.0, 0.0),
                "c2": (2.0, 0.0, 0.0),
            },
        )
        sidebar = SidebarCoordinator(
            project_read_service=SimpleNamespace(),
            ui_state_manager=SimpleNamespace(active_page_uid="p1"),
            project_data=project_data,
        )
        sidebar.conditions_sidebar = SimpleNamespace(
            update_quantities=lambda quantities: quantity_payloads.append(quantities)
        )
        sidebar.update_conditions_quantities()
        self.assertEqual(
            quantity_payloads,
            [{"c1": (1.0, 0.0, 0.0), "c2": (2.0, 0.0, 0.0)}],
        )

    def test_sidebar_quantity_update_accepts_partial_condition_uids(self):
        quantity_calls = []
        sidebar_calls = []

        def compute_quantities(page_uids, only_condition_uids=None):
            quantity_calls.append((list(page_uids), set(only_condition_uids or [])))
            return {uid: (3.0, 0.0, 0.0) for uid in only_condition_uids or []}

        project_data = SimpleNamespace(
            get_selected_page_uids=lambda: ["p1"],
            compute_quantities_for_pages=compute_quantities,
        )
        sidebar = SidebarCoordinator(
            project_read_service=SimpleNamespace(),
            ui_state_manager=SimpleNamespace(active_page_uid="p1"),
            project_data=project_data,
        )
        sidebar.conditions_sidebar = SimpleNamespace(
            update_quantities=lambda quantities, partial=False: sidebar_calls.append(
                (dict(quantities), partial)
            )
        )
        sidebar.update_conditions_quantities(condition_uids=["c2"])
        self.assertEqual(quantity_calls, [(["p1"], {"c2"})])
        self.assertEqual(sidebar_calls, [({"c2": (3.0, 0.0, 0.0)}, True)])
