import os
import sqlite3
import unittest
from types import SimpleNamespace
from ost_visualizer.domain.entities.project_factory import build_bid
from ost_visualizer.presentation.components.plan_view.view import TakeoffPlanView
from ost_visualizer.presentation.coordinators.viewer_sync_coordinator import (
    ViewerSyncCoordinator,
)
from tests.infrastructure.mdb.components.test_hierarchy_reader import (
    _SqliteConnection,
    _SqliteHierarchyReader,
)
from tests.presentation.components.plan_view.overlay_support import (
    FakeColorService,
    FakePlanView,
    FakeProjectData,
    FakeUiState,
)

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


class _SnapRecordingPlanView(FakePlanView):
    def __init__(self):
        super().__init__(current_page_uid="page-1", overlay_result=True)
        self._snap_increments = None

    def set_snap_settings(self, increments, measure_base):
        super().set_snap_settings(increments, measure_base)
        TakeoffPlanView.set_snap_settings(self, increments, measure_base)


class StoredTakeoffIncrementReachesPlanViewTests(unittest.TestCase):
    def _loaded_bid(self, measure_base, takeoff_increments):
        connection = sqlite3.connect(":memory:")
        self.addCleanup(connection.close)
        connection.execute("CREATE TABLE BidProjects (UID INTEGER, Name TEXT)")
        connection.execute(
            "CREATE TABLE Bids (UID INTEGER, BidProjectUID INTEGER, JobName TEXT, "
            "MeasureBase INTEGER, TakeoffIncrements REAL)"
        )
        connection.execute("CREATE TABLE BidPages (UID INTEGER, BidUID INTEGER)")
        connection.execute("CREATE TABLE BidConditions (UID INTEGER, BidUID INTEGER)")
        connection.execute("INSERT INTO BidProjects VALUES (1, 'Project')")
        connection.execute(
            "INSERT INTO Bids VALUES (7, 1, 'Bid', ?, ?)",
            (measure_base, takeoff_increments),
        )
        entry = _SqliteHierarchyReader(connection)._parse_hierarchy(
            _SqliteConnection(connection), "C:/data/snap.mdb"
        )
        return build_bid(entry.bid_projects["1"].bids[0])

    def _snap_after_page_update(self, bid):
        project_data = FakeProjectData()
        project_data.bid = bid
        plan_view = _SnapRecordingPlanView()
        coordinator = ViewerSyncCoordinator(
            ui_state_manager=FakeUiState(),
            ui_access_manager=None,
            color_service=FakeColorService(),
            project_data=project_data,
            callback_bridge=SimpleNamespace(
                dispatch=lambda callback, payload: callback(payload)
            ),
        )
        coordinator.plan_view = plan_view
        coordinator.update_plan_view("page-1")
        return plan_view

    def test_a_stored_zero_increment_turns_snapping_off_in_the_plan_view(self):
        for measure_base in (0, 1):
            with self.subTest(measure_base=measure_base):
                plan_view = self._snap_after_page_update(
                    self._loaded_bid(measure_base, 0.0)
                )
                self.assertEqual(plan_view.snap_settings, [(0.0, measure_base)])
                self.assertEqual(plan_view._snap_increments, 0.0)

    def test_a_missing_increment_still_snaps_to_the_default(self):
        cases = (
            (0, None, 1.0),
            (1, None, 1.0 / 25.4),
            (0, 0.25, 0.25),
            (1, 10.0, 10.0 / 25.4),
        )
        for measure_base, stored, expected in cases:
            with self.subTest(measure_base=measure_base, stored=stored):
                plan_view = self._snap_after_page_update(
                    self._loaded_bid(measure_base, stored)
                )
                self.assertAlmostEqual(plan_view._snap_increments, expected)


if __name__ == "__main__":
    unittest.main()
