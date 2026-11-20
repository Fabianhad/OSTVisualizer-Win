import os
import sqlite3
import unittest
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from ost_visualizer.application.services.project_read_service import (
    ProjectReadService,
)
from ost_visualizer.domain.entities.condition import Condition
from ost_visualizer.domain.entities.identity_refs import BidRef
from ost_visualizer.domain.entities.layer import is_layer_visible
from ost_visualizer.domain.entities.page import Page
from ost_visualizer.presentation.components.layers_sidebar import BidLayersSidebar
from ost_visualizer.presentation.coordinators.ui_event_coordinator import (
    UIEventCoordinator,
)
from tests.domain.services.test_project_data_service import _real_service
from tests.helpers.mdb.operations import _SqliteConnectionWrapper, _SqliteDuplicateOps
from tests.infrastructure.mdb.components.test_bid_data_reader import _SqliteBidReader
from tests.presentation.coordinators.test_ui_event_coordinator import (
    _sp3a5i_INTERNAL,
    _sp3a5i_stub_all,
)
from tests.presentation.dialogs.master_data_support import _app

_LAYER_ROWS = (
    (1, None, "Image", -1, 0, -1, -1),
    (2, None, "Default", 0, 2, -1, -1),
    (3, None, "Annotation", -1, 1, -1, -1),
    (13, 7, "Annotation", -1, 1, -1, -1),
    (10, 7, "Walls", -1, 5, 0, 0),
    (20, 8, "Other", -1, 5, 0, 0),
)


class _WriteThroughPersistence:
    def __init__(self, connection):
        self._ops = _SqliteDuplicateOps(connection)
        self.captured = []

    def has_all_layers_show_revision(self, *_args):
        return False

    def schedule_all_layers_show(self, db_path, bid_uid, show, layer_uids, **_hooks):
        self.captured.append(list(layer_uids))
        return bool(
            self._ops.update_all_layers_show(db_path, bid_uid, show, list(layer_uids))
        )


class HideAllSharedLayerAgreementTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _app()

    def setUp(self):
        self.connection = sqlite3.connect(":memory:")
        self.addCleanup(self.connection.close)
        self.connection.execute("CREATE TABLE Bids (UID INTEGER)")
        self.connection.executemany("INSERT INTO Bids VALUES (?)", [(7,), (8,)])
        self.connection.execute(
            "CREATE TABLE BidLayers (UID INTEGER, BidUID INTEGER, Name TEXT, "
            "Show INTEGER, Sequence INTEGER, IsTemplate INTEGER, IsLocked INTEGER)"
        )
        self.connection.executemany(
            "INSERT INTO BidLayers VALUES (?, ?, ?, ?, ?, ?, ?)", _LAYER_ROWS
        )
        self.reader = _SqliteBidReader(self.connection)
        self.read_service = ProjectReadService(self.reader)
        self.ref = BidRef("bid.mdb", "7")
        self.service, self.aggregate = _real_service()
        self.aggregate.current_bid_ref = self.ref
        merged = self.read_service.get_merged_bid_layers("bid.mdb", "7")
        self.service.set_bid_layer_visibility(merged)
        own_layers = self._own_layers()
        self.aggregate.bid_conditions = {
            uid: Condition(
                uid=uid,
                layer_uid=layer_uid,
                layer_visible=is_layer_visible(own_layers, layer_uid),
            )
            for uid, layer_uid in (
                ("walls", "10"),
                ("default", "2"),
                ("annotation", "13"),
                ("image", "1"),
                ("none", None),
            )
        }
        self.page = Page("p", "P", layer_visible=True)
        self.aggregate.set_pages({"p": self.page})
        self.sidebar = BidLayersSidebar(None)
        self.addCleanup(self.sidebar.deleteLater)
        self.sidebar.load_layers(merged)
        self.persistence = _WriteThroughPersistence(self.connection)
        self.coordinator = self._coordinator()

    def _own_layers(self):
        return self.reader._parse_bid_layers_for_bid(
            _SqliteConnectionWrapper(self.connection), "7"
        )

    def _coordinator(self):
        coordinator = UIEventCoordinator.__new__(UIEventCoordinator)
        coordinator.log = []
        owner = object()
        self.service.get_bid = lambda _ref: owner
        coordinator.project_data = self.service
        coordinator.ui_access_manager = SimpleNamespace(is_allowed=lambda _f: True)
        coordinator.ui_state_manager = SimpleNamespace(
            get_selected_bid_ref=lambda: self.ref, active_page_uid="p"
        )
        coordinator._project_write_service = SimpleNamespace(
            uses_sql_collaboration_mutations=lambda _db_path: False
        )
        coordinator._project_read_service = self.read_service
        coordinator._sidebar = SimpleNamespace(bid_layers_sidebar=self.sidebar)
        coordinator._deferred_persistence = self.persistence
        coordinator.event_bus = SimpleNamespace(publish=lambda *_a, **_k: None)
        _sp3a5i_stub_all(coordinator, *_sp3a5i_INTERNAL)
        return coordinator

    def _assert_memory_sidebar_and_reload_agree(self, expected):
        reloaded = {
            layer.uid: layer.show
            for layer in self.read_service.get_merged_bid_layers("bid.mdb", "7")
        }
        sidebar = {
            layer.uid: self.sidebar.get_layer_visibility(layer.uid)
            for layer in self.sidebar.get_layers()
        }
        self.assertEqual(reloaded, expected)
        self.assertEqual(self.aggregate.bid_layer_visibility, expected)
        self.assertEqual(sidebar, expected)
        own_layers = self._own_layers()
        self.assertEqual(
            {c.uid: c.layer_visible for c in self.aggregate.bid_conditions.values()},
            {
                c.uid: is_layer_visible(own_layers, c.layer_uid)
                for c in self.aggregate.bid_conditions.values()
            },
        )
        self.assertIs(self.page.layer_visible, True)
        self.assertEqual(
            self.connection.execute(
                "SELECT UID, Show FROM BidLayers WHERE BidUID IS NULL OR BidUID = 8 "
                "ORDER BY UID"
            ).fetchall(),
            [(1, -1), (2, 0), (3, -1), (20, -1)],
        )

    def test_hide_all_and_show_all_change_only_the_bids_own_layers_everywhere(self):
        self.assertTrue(self.coordinator.update_all_layers_visibility_deferred(False))
        self.assertEqual(self.persistence.captured, [["13", "10"]])
        self._assert_memory_sidebar_and_reload_agree(
            {"1": True, "13": False, "2": False, "10": False}
        )
        self.assertEqual(
            {c.uid: c.layer_visible for c in self.aggregate.bid_conditions.values()},
            {
                "walls": False,
                "default": True,
                "annotation": False,
                "image": True,
                "none": True,
            },
        )
        self.assertTrue(self.coordinator.update_all_layers_visibility_deferred(True))
        self.assertEqual(self.persistence.captured[-1], ["13", "10"])
        self._assert_memory_sidebar_and_reload_agree(
            {"1": True, "13": True, "2": False, "10": True}
        )


if __name__ == "__main__":
    unittest.main()
