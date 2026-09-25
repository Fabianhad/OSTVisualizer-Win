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


class PageScaleSurfaceSyncRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def _make_refresh_coordinator(
        self,
        *,
        initial_pages: list[Page],
        refreshed_pages: list[Page],
        selected_page_uids: list[str],
        active_page_uid: str | None,
    ) -> tuple[UIEventCoordinator, PageComboBox, list[tuple[str | None, Page | None]]]:
        bid_ref = BidRef("scale-sync.mdb", "7")
        initial_bid = Bid(uid="7", name="Bid", pages_without_folder=list(initial_pages))
        refreshed_bid = Bid(
            uid="7", name="Bid", pages_without_folder=list(refreshed_pages)
        )
        pages_by_uid = {page.uid: page for page in refreshed_pages}
        page_combo = PageComboBox()
        page_combo.load_bid(initial_bid)
        page_combo.restore_selection(selected_page_uids, active_page_uid)
        sidebar = _RefreshSidebar(page_combo, refreshed_bid)
        projected: list[tuple[str | None, Page | None]] = []

        class UiState:
            highlighted_condition_uids = set()
            selected_area_uid = ""
            place_condition_uid = None
            place_condition_uids = []

            def __init__(self) -> None:
                self.selected_page_uids = list(selected_page_uids)
                self.active_page_uid = active_page_uid

            def get_selected_bid_ref(self):
                return bid_ref

            def set_highlighted_conditions(self, _uids) -> None:
                pass

            def set_page_selection(self, page_uids) -> None:
                self.selected_page_uids = list(page_uids)

        ui_state = UiState()
        project_data = SimpleNamespace(
            get_current_file_path=lambda: bid_ref.file_path,
            get_bid=lambda ref: refreshed_bid if ref == bid_ref else None,
            get_current_bid_ref=lambda: bid_ref,
            get_bid_conditions=lambda: {},
            get_area_uids_with_takeoff=lambda: set(),
            get_page=lambda uid: pages_by_uid.get(uid),
            get_all_pages=lambda: list(refreshed_pages),
            get_selected_page_uids=lambda: list(ui_state.selected_page_uids),
            get_last_selected_page_uid=lambda: active_page_uid,
            select_pages=lambda page_uids: list(page_uids),
        )
        snapshot = SimpleNamespace(
            bid_ref=bid_ref,
            page_uids=list(selected_page_uids),
            active_page_uid=active_page_uid,
            highlighted_condition_uids=set(),
            project_uid=None,
            database_selected=False,
            selected_file_path=bid_ref.file_path,
            place_condition_uid=None,
            place_condition_uids=[],
            selected_area_uid="",
        )

        class Nav:
            refresh_snapshot = snapshot

            def finish_refresh(self, _state) -> None:
                pass

            def compute_state_for(self, **_kwargs):
                return "BID_ACTIVE"

        coordinator = UIEventCoordinator.__new__(UIEventCoordinator)
        coordinator.plan_view = None
        coordinator.ui_state_manager = ui_state
        coordinator.project_data = project_data
        coordinator.takeoff_sidebar = page_combo
        coordinator._sidebar = sidebar
        coordinator._project_write_service = SimpleNamespace(
            uses_sql_collaboration_mutations=lambda _database_id: False
        )
        coordinator._page_settings_bar = None
        coordinator._takeoff_workspace_bid_ref = bid_ref
        coordinator._pending_takeoff_page_uids = None
        coordinator._pending_takeoff_active_page_uid = None
        coordinator._pending_takeoff_selected_area_uid = ""
        coordinator._pending_takeoff_place_condition_uid = None
        coordinator._pending_takeoff_place_condition_uids = []
        coordinator._selected_takeoff_uids = ()
        coordinator._selection_projected_condition_uids = set()
        coordinator._last_takeoff_selection_context_by_source = {}
        coordinator._tab_widget = SimpleNamespace(
            currentIndex=lambda: TAB_INDEX_TAKEOFF
        )
        coordinator._viewer = SimpleNamespace(clear_plan_view=lambda: None)
        coordinator._status_panel = None
        coordinator._nav = Nav()
        coordinator._resolve_bid_lock_state = lambda _bid_ref: None
        coordinator._is_condition_placeable = lambda _uid: False
        coordinator._reset_to_select_mode = lambda: None
        coordinator._load_takeoff_sidebar = lambda _bid_ref: page_combo.load_bid(
            refreshed_bid
        )
        coordinator._load_condition_summary = lambda: None
        coordinator._restore_sidebar_highlight = lambda _uids, reveal=True: None
        coordinator._sync_embedded_renderer_exposure = lambda: None
        coordinator._update_menu_state = lambda: None
        coordinator._update_export_menu_state = lambda: None
        coordinator.main_window = SimpleNamespace(
            project_view=SimpleNamespace(restore_bid_selection=lambda _bid_ref: None),
            notify_takeoff_workspace_activated=lambda: None,
            refresh_window_title=lambda: None,
        )
        coordinator.ui_access_manager = SimpleNamespace(refresh=lambda: None)

        def project_active_page(page_uid: str | None) -> None:
            ui_state.active_page_uid = page_uid
            projected.append((page_uid, pages_by_uid.get(page_uid)))

        coordinator.handle_active_page_changed = project_active_page
        page_combo.active_page_changed.connect(project_active_page)
        return coordinator, page_combo, projected

    def test_same_active_page_refresh_projects_authoritative_scale_once(self) -> None:
        original = Page(
            uid="page-1",
            name="A101",
            scale_factor1=0.125,
            scale_factor2=12.0,
        )
        authoritative = Page(
            uid="page-1",
            name="A101",
            scale_factor1=0.25,
            scale_factor2=12.0,
        )
        coordinator, page_combo, projected = self._make_refresh_coordinator(
            initial_pages=[original],
            refreshed_pages=[authoritative],
            selected_page_uids=[original.uid],
            active_page_uid=original.uid,
        )
        self.addCleanup(page_combo.close)
        coordinator._selected_takeoff_uids = ("takeoff-1",)
        coordinator._finish_refresh()
        self.assertEqual(projected, [(authoritative.uid, authoritative)])
        self.assertEqual(projected[0][1].scale_factor1, 0.25)
        self.assertEqual(page_combo.get_active_page_uid(), authoritative.uid)
        self.assertEqual(coordinator._selected_takeoff_uids, ("takeoff-1",))

    def test_changed_active_page_projects_once_without_duplicate_reload(self) -> None:
        original = Page(uid="page-1", name="A101")
        replacement = Page(uid="page-2", name="A102", scale_factor1=0.25)
        coordinator, page_combo, projected = self._make_refresh_coordinator(
            initial_pages=[original],
            refreshed_pages=[replacement],
            selected_page_uids=[original.uid],
            active_page_uid=original.uid,
        )
        self.addCleanup(page_combo.close)
        coordinator._finish_refresh()
        self.assertEqual(projected, [(replacement.uid, replacement)])
        self.assertEqual(page_combo.get_active_page_uid(), replacement.uid)

    def test_page_combo_reports_whether_active_page_signal_was_emitted(self) -> None:
        page = Page(uid="page-1", name="A101")
        combo = PageComboBox()
        self.addCleanup(combo.close)
        combo.load_bid(Bid(uid="7", name="Bid", pages_without_folder=[page]))
        emitted = []
        combo.active_page_changed.connect(emitted.append)
        self.assertTrue(combo.restore_selection([page.uid], page.uid))
        self.assertFalse(combo.restore_selection([page.uid], page.uid))
        self.assertEqual(emitted, [page.uid])

    def test_authoritative_rescale_preserves_display_geometry_without_hybrid_jump(
        self,
    ) -> None:
        source_scale = (0.125, 12.0)
        target_scale = (0.25, 12.0)
        source_position = [960.0, 480.0, 1920.0, 960.0]
        target_position = rescale_position_between_page_scales(
            source_position, source_scale, target_scale
        )
        source_coordinates = OSTCoordinateSystem(
            {"scale_factor1": source_scale[0], "scale_factor2": source_scale[1]}
        )
        target_coordinates = OSTCoordinateSystem(
            {"scale_factor1": target_scale[0], "scale_factor2": target_scale[1]}
        )
        source_display = source_coordinates.transform_vertices_to_2d(source_position)
        target_display = target_coordinates.transform_vertices_to_2d(target_position)
        stale_hybrid_display = target_coordinates.transform_vertices_to_2d(
            source_position
        )
        self.assertEqual(target_position, [480.0, 240.0, 960.0, 480.0])
        self.assertEqual(target_display, source_display)
        self.assertNotEqual(stale_hybrid_display, source_display)

    def test_scale_refresh_skips_project_tree_rebuild_and_preserves_tool_contract(
        self,
    ) -> None:
        calls = []
        bid_ref = BidRef("scale-sync.mdb", "7")
        coordinator = UIEventCoordinator.__new__(UIEventCoordinator)
        coordinator._deferred_persistence = SimpleNamespace(
            cancel_for_file=lambda _path: None
        )
        coordinator._flush_deferred_for_file = lambda _path: True
        coordinator._nav = SimpleNamespace(start_refresh=lambda *_args, **_kwargs: True)
        coordinator._placement = SimpleNamespace()
        coordinator.ui_state_manager = SimpleNamespace(
            selected_area_uid="",
            selected_page_uids=["page-1"],
            get_selected_bid_ref=lambda: bid_ref,
        )
        coordinator.project_data = SimpleNamespace(
            get_selected_page_uids=lambda: ["page-1"]
        )
        coordinator._clear_mesh_views_for_scene_update = lambda: calls.append(
            "clear-mesh"
        )
        coordinator._mark_mesh_scene_dirty = lambda pages: calls.append(
            ("dirty-mesh", tuple(pages))
        )
        coordinator._do_file_refresh = (
            lambda *, rebuild_project_tree=True: calls.append(
                ("refresh", rebuild_project_tree)
            )
        )
        coordinator._finish_refresh = (
            lambda *, accept_reconstructed_placement_conditions=False: calls.append(
                ("finish", accept_reconstructed_placement_conditions)
            )
        )
        coordinator._flush_dirty_mesh_refresh_if_needed = lambda: calls.append(
            "flush-mesh"
        )

        coordinator._on_database_refreshed(
            file_path=bid_ref.file_path,
            image_sources_unchanged=True,
            page_scale_uids=("page-1",),
        )

        self.assertIn(("refresh", False), calls)
        self.assertIn(("finish", True), calls)
        self.assertIn(("dirty-mesh", ("page-1",)), calls)

    def test_scale_refresh_rebuilds_bid_cache_without_rebuilding_project_tree(
        self,
    ) -> None:
        coordinator = UIEventCoordinator.__new__(UIEventCoordinator)
        hierarchy = object()
        loaded_files = object()
        cached = []
        rebuilt = []
        coordinator.project_data = SimpleNamespace(get_hierarchy=lambda: hierarchy)
        coordinator._cache_bid_data = cached.append
        coordinator.main_window = SimpleNamespace(
            project_view=SimpleNamespace(
                build_complete_structure=rebuilt.append,
            )
        )

        with patch(
            "ost_visualizer.presentation.coordinators.ui_event_coordinator.build_loaded_files",
            return_value=loaded_files,
        ):
            coordinator._do_file_refresh(rebuild_project_tree=False)

        self.assertEqual(cached, [loaded_files])
        self.assertEqual(rebuilt, [])

    def test_scale_refresh_rebinds_reconstructed_conditions_without_select_reset(
        self,
    ) -> None:
        page = Page(uid="page-1", name="A101", scale_factor1=0.25)
        coordinator, page_combo, _projected = self._make_refresh_coordinator(
            initial_pages=[page],
            refreshed_pages=[page],
            selected_page_uids=[page.uid],
            active_page_uid=page.uid,
        )
        self.addCleanup(page_combo.close)
        accepted_reconstruction = []
        select_resets = []
        coordinator._nav.refresh_snapshot.place_condition_uid = "condition-1"
        coordinator._nav.refresh_snapshot.place_condition_uids = ["condition-1"]
        coordinator.project_data.get_bid_conditions = lambda: {"condition-1": object()}
        coordinator._is_condition_placeable = lambda uid: uid == "condition-1"
        coordinator._set_plan_select_mode = lambda: select_resets.append(True)
        coordinator._tab_widget = None

        class Placement:
            is_active = True

            @staticmethod
            def reconcile_authoritative_conditions(
                *, accept_reconstructed_conditions=False
            ):
                accepted_reconstruction.append(accept_reconstructed_conditions)
                return accept_reconstructed_conditions

        coordinator._placement = Placement()

        coordinator._finish_refresh(accept_reconstructed_placement_conditions=True)

        self.assertEqual(accepted_reconstruction, [True])
        self.assertEqual(select_resets, [])
        self.assertEqual(
            coordinator._pending_takeoff_place_condition_uid,
            "condition-1",
        )

    def test_select_mode_remains_select_during_scale_refresh(self) -> None:
        page = Page(uid="page-1", name="A101", scale_factor1=0.25)
        coordinator, page_combo, _projected = self._make_refresh_coordinator(
            initial_pages=[page],
            refreshed_pages=[page],
            selected_page_uids=[page.uid],
            active_page_uid=page.uid,
        )
        self.addCleanup(page_combo.close)
        reconcile_calls = []

        class Placement:
            is_active = False

            @staticmethod
            def reconcile_authoritative_conditions(
                *, accept_reconstructed_conditions=False
            ):
                reconcile_calls.append(accept_reconstructed_conditions)
                return True

        coordinator._placement = Placement()
        coordinator._finish_refresh(accept_reconstructed_placement_conditions=True)

        self.assertEqual(reconcile_calls, [])
        self.assertIsNone(coordinator._pending_takeoff_place_condition_uid)


if __name__ == "__main__":
    unittest.main()
