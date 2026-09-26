import unittest
from types import SimpleNamespace
from unittest.mock import Mock
from ost_visualizer.domain.aggregates.ost_aggregate import OstAggregate
from ost_visualizer.domain.entities.annotation import (
    ANNOTATION_TYPE_TEXT,
    BidAnnotation,
)
from ost_visualizer.domain.entities.area import BidArea, UNASSIGNED_AREA_UID
from ost_visualizer.domain.entities.bid import Bid
from ost_visualizer.domain.entities.identity_refs import BidRef
from ost_visualizer.domain.entities.page import Page
from ost_visualizer.domain.entities.takeoff import Takeoff
from ost_visualizer.domain.services.project_data_service import ProjectDataService
from ost_visualizer.presentation.coordinators.ui_event_coordinator import (
    UIEventCoordinator,
)
from ost_visualizer.presentation.coordinators.viewer_sync_coordinator import (
    ViewerSyncCoordinator,
)
from ost_visualizer.presentation.managers.detached_page_view_manager import (
    DetachedPageViewManager,
)


class PageScaleProjectionTests(unittest.TestCase):
    def _data(self):
        bid_ref = BidRef("scale.mdb", "7")
        takeoff = Takeoff("10", "20", page_uid="42", position=[20.0, 40.0])
        page = Page(
            "42",
            "A101",
            takeoffs=[takeoff],
            scale_factor1=1.0,
            scale_factor2=10.0,
            overlay_rect=(2.0, 4.0, 6.0, 8.0),
            overlay_offset_x=2.0,
            overlay_offset_y=4.0,
        )
        annotation = BidAnnotation(
            "30",
            ANNOTATION_TYPE_TEXT,
            page_uid="42",
            position=[2.0, 4.0, 6.0, 8.0, 33.0],
        )
        model = OstAggregate(SimpleNamespace())
        model.current_bid_ref = bid_ref
        model.current_bid = Bid("7", "Bid")
        model.bid_takeoffs = [takeoff]
        model.set_pages({page.uid: page})
        model.set_annotations([annotation])
        return ProjectDataService(model), bid_ref, page, takeoff, annotation

    def test_committed_scale_projects_only_scale_dependent_model_state(self):
        data, bid_ref, page, takeoff, annotation = self._data()
        changed = data.apply_page_scales(bid_ref, [page], 1.0, 20.0)
        self.assertEqual(changed, (page.uid,))
        self.assertEqual((page.scale_factor1, page.scale_factor2), (1.0, 20.0))
        self.assertEqual(takeoff.position, [40.0, 80.0])
        self.assertEqual(annotation.position, [4.0, 8.0, 12.0, 16.0, 33.0])
        self.assertEqual(page.overlay_rect, (4.0, 8.0, 12.0, 16.0))
        self.assertEqual((page.overlay_offset_x, page.overlay_offset_y), (4.0, 8.0))

    def test_scale_projection_rejects_another_bid_without_mutation(self):
        data, _bid_ref, page, takeoff, annotation = self._data()
        changed = data.apply_page_scales(BidRef("scale.mdb", "8"), [page], 1.0, 20.0)
        self.assertEqual(changed, ())
        self.assertEqual(page.scale_factor2, 10.0)
        self.assertEqual(takeoff.position, [20.0, 40.0])
        self.assertEqual(annotation.position[-1], 33.0)

    def test_scale_event_refreshes_only_affected_surfaces(self):
        calls = []
        bid_ref = BidRef("scale.mdb", "7")
        coordinator = UIEventCoordinator.__new__(UIEventCoordinator)
        coordinator.ui_state_manager = SimpleNamespace(
            active_page_uid="42",
            get_selected_bid_ref=lambda: bid_ref,
        )
        coordinator.project_data = SimpleNamespace(
            get_selected_page_uids=lambda: ["42", "43"]
        )
        coordinator._update_page_settings_bar = lambda uid: calls.append(("bar", uid))
        coordinator._viewer = SimpleNamespace(
            update_plan_view=lambda uid, **kwargs: calls.append(("plan", uid, kwargs))
        )
        coordinator._apply_pending_hotlink_named_view_focus = (
            lambda require_stable: calls.append(("hotlink", require_stable))
        )
        coordinator._request_or_defer_mesh_refresh = lambda uids: calls.append(
            ("mesh", tuple(uids))
        )
        coordinator._sidebar = Mock()
        coordinator._is_summary_tab_active = lambda: False
        coordinator._on_page_metadata_changed("scale.mdb", "7", ("42",), ("scale",))
        self.assertEqual(calls[0], ("bar", "42"))
        self.assertEqual(calls[1], ("plan", "42", {"force_overlay_refresh": True}))
        self.assertIn(("mesh", ("42", "43")), calls)


class PageAreaProjectionTests(unittest.TestCase):
    def test_viewer_projects_page_area_without_recapturing_page_graph(self):
        selections = {"42": "area-2"}
        calls = []
        viewer = ViewerSyncCoordinator.__new__(ViewerSyncCoordinator)
        viewer._project_data = SimpleNamespace(
            get_page_area_selections=lambda: selections
        )
        viewer.plan_view = SimpleNamespace(
            current_page_uid="42",
            refresh_page_area_selection=lambda value: calls.append(value) or True,
        )
        self.assertTrue(viewer.update_page_area_selection("42"))
        self.assertEqual(calls, [selections])

    def test_detached_area_refresh_uses_overlay_only_for_matching_page(self):
        calls = []
        bid_ref = BidRef("areas.mdb", "7")
        view = SimpleNamespace(target_page_uid="42", bid_ref=bid_ref)
        manager = DetachedPageViewManager.__new__(DetachedPageViewManager)
        manager.repository = SimpleNamespace(get_active_view=lambda: view)
        manager.project_data = SimpleNamespace(get_current_bid_ref=lambda: bid_ref)
        manager._window = SimpleNamespace(
            update_page_area_selection=lambda data: calls.append(data)
        )
        manager._get_page_data = lambda current: ("page-data", current)
        manager.refresh_page_area_selection("41")
        manager.refresh_page_area_selection("42")
        self.assertEqual(calls, [("page-data", view)])

    def test_local_area_refresh_clears_only_deleted_area_references(self):
        bid_ref = BidRef("areas.mdb", "7")
        removed = Takeoff("1", "10", page_uid="42", area_uid="20")
        retained = Takeoff("2", "10", page_uid="42", area_uid="21")
        page = Page("42", "A101", takeoffs=[removed, retained])
        model = OstAggregate(SimpleNamespace())
        model.current_bid_ref = bid_ref
        model.current_bid = Bid("7", "Bid")
        model.bid_takeoffs = [removed, retained]
        model.page_area_selections = {"42": "20", "43": "21"}
        model.set_pages({page.uid: page})
        data = ProjectDataService(model)
        applied = data.replace_bid_areas_after_local_save(
            bid_ref,
            [BidArea("21", "7", "", "Retained", 1)],
            ["20"],
        )
        self.assertTrue(applied)
        self.assertIsNone(model.page_area_selections["42"])
        self.assertEqual(model.page_area_selections["43"], "21")
        self.assertEqual(removed.area_uid, UNASSIGNED_AREA_UID)
        self.assertEqual(retained.area_uid, "21")


if __name__ == "__main__":
    unittest.main()
