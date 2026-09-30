import os
import unittest
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from ost_visualizer.application.dtos.collaboration_resource_catalog import (
    CollaborationResourceFamily,
    CollaborationResourceType,
)
from ost_visualizer.application.dtos.remote_projection_dtos import (
    RemoteProjectionBarrier,
)
from ost_visualizer.domain.entities.condition import Condition
from ost_visualizer.domain.entities.identity_refs import BidRef
from ost_visualizer.domain.entities.page import Page
from ost_visualizer.domain.entities.takeoff import Takeoff
from ost_visualizer.presentation.config import (
    TAB_INDEX_PROJECTS,
    TAB_INDEX_SUMMARY,
    TAB_INDEX_TAKEOFF,
)
from ost_visualizer.presentation.coordinators.ui_event_coordinator import (
    UIEventCoordinator,
    _MeshScenePublication,
)
from ost_visualizer.presentation.managers.ui_access_manager import Feature
from PySide6 import QtWidgets
from shiboken6 import delete
from tests.presentation.coordinators.ui_event_coordinator_support import (
    FakeMainWindow,
    FakeMenuController,
    FakeMeshAccess,
    FakePageSettingsBar,
    FakeProjectData,
    FakeProjectView,
    FakeSidebar,
    FakeTabWidget,
    FakeTakeoffSidebar,
    FakeToolbar,
    FakeUiState,
    FakeViewStack,
    FakeViewer,
    FakeVisualization,
    configure_mesh_state,
)


class AggregateProjectionWorkflowTests(unittest.TestCase):
    def test_mixed_area_layer_takeoff_batch_refreshes_each_aggregate_once(self):
        database_id = "sql-db"
        bid_uid = "bid-1"

        class SelectedUiState(FakeUiState):
            def get_selected_bid_ref(self):
                return BidRef(database_id, bid_uid)

        coordinator = UIEventCoordinator.__new__(UIEventCoordinator)
        coordinator.ui_state_manager = SelectedUiState()
        coordinator.project_data = FakeProjectData()
        coordinator.takeoff_sidebar = FakeTakeoffSidebar()
        coordinator._page_settings_bar = FakePageSettingsBar()
        coordinator._viewer = FakeViewer()
        coordinator._sidebar = FakeSidebar()
        coordinator._toolbar = FakeToolbar()
        coordinator.main_window = FakeMainWindow()
        coordinator.plan_view = SimpleNamespace(
            has_active_remote_projection_blocker=lambda: False
        )
        coordinator._plan_view_handler = None
        coordinator._is_cleaning_up = False
        coordinator._undo_service = None
        coordinator._selected_takeoff_uids = ()
        coordinator._pending_hotlink_page_uid = None
        coordinator._pending_hotlink_named_view = None
        coordinator._restore_project_tree_bid_selection_if_needed = lambda: None
        configure_mesh_state(coordinator, view_index=0)
        self.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
        from ost_visualizer.application.dtos.condition_summary_dtos import (
            ConditionSummaryGrouping,
        )
        from ost_visualizer.application.use_cases.project.condition_summary_service import (
            ConditionSummaryService,
        )
        from ost_visualizer.domain.entities.bid import Bid
        from ost_visualizer.domain.services.condition_quantity_service import (
            compute_page_quantities,
        )
        from ost_visualizer.presentation.components.conditions_sidebar import (
            ConditionsSidebar,
        )
        from ost_visualizer.presentation.coordinators.sidebar_coordinator import (
            SidebarCoordinator,
        )

        widget = ConditionsSidebar(None)
        self.addCleanup(lambda: delete(widget))
        conditions = {
            "c1": Condition("c1", name="Updated", condition_type=2, calc_type1=23)
        }
        takeoffs = [
            Takeoff("t1", "c1", "page-1", position=[0, 0]),
            Takeoff("t2", "c1", "page-2", position=[10, 10]),
        ]
        quantities = []
        summaries = []

        def calculate(pages, only_condition_uids=None):
            quantities.append(tuple(pages))
            return compute_page_quantities(
                conditions,
                [t for t in takeoffs if t.page_uid in pages],
                only_condition_uids,
            )

        data = coordinator.project_data
        data.selected_page_uids = ["page-1", "page-2"]
        data.compute_quantities_for_pages = calculate
        data.has_takeoffs_for_pages = lambda pages: any(
            t.page_uid in pages for t in takeoffs
        )
        data.get_bid_conditions = lambda: conditions
        data.get_bid_condition_folders = lambda: {}
        data.get_bid = lambda ref: Bid("bid-1", "Bid")
        data.get_bid_layer_snapshot = lambda: []
        data.get_cdn_types = lambda: {}
        data.get_all_takeoffs = lambda: takeoffs
        data.get_all_pages = lambda: [Page("page-1", "First"), Page("page-2", "Second")]
        data.get_bid_area_snapshot = lambda: []
        state = coordinator.ui_state_manager
        state.highlighted_condition_uids = set()
        state.set_highlighted_conditions = lambda uids: None
        state.state = SimpleNamespace(grayscale_enabled=False)
        sidebar = SidebarCoordinator.__new__(SidebarCoordinator)
        sidebar.conditions_sidebar = widget
        sidebar._project_data = data
        sidebar._ui_state = state
        sidebar._view_stack = coordinator._view_stack
        sidebar._condition_summary_service = ConditionSummaryService()
        sidebar.condition_summary_tab = SimpleNamespace(
            grouping=ConditionSummaryGrouping(),
            load_summary=lambda root, *args: summaries.append(root),
        )
        coordinator._sidebar = sidebar
        coordinator._reconcile_active_placement = lambda **_kwargs: None
        coordinator._restore_sidebar_highlight = lambda *args, **kwargs: None
        coordinator._is_summary_tab_active = lambda: True
        coordinator._load_condition_summary = sidebar.load_condition_summary_from_memory
        scans = []
        page_scans = []
        layer_loads = []
        rebuilds = []
        area_loads = []
        data.get_area_uids_with_takeoff = lambda: scans.append(True) or {"area-new"}
        data.get_area_uids_with_takeoff_for_page = lambda uid: {"area-new"}
        data.has_takeoffs_for_pages = lambda pages: page_scans.append(
            tuple(pages)
        ) or any(t.page_uid in pages for t in takeoffs)
        data.get_layer_uids_in_use = lambda: set()
        sidebar.bid_layers_sidebar = SimpleNamespace(
            load_layers=lambda *args, **kwargs: layer_loads.append(True)
        )
        original_rebuild = sidebar.refresh_conditions_from_memory

        def rebuild():
            rebuilds.append(True)
            original_rebuild()

        sidebar.refresh_conditions_from_memory = rebuild
        coordinator._page_settings_bar.get_selected_area_uid = lambda: ""
        coordinator._page_settings_bar.load_bid_areas = (
            lambda *args, **kwargs: area_loads.append(kwargs["areas_with_takeoff"])
        )
        coordinator._deferred_persistence = SimpleNamespace(
            reproject_newer_layer_visual_revisions=lambda *args: None,
            invalidate_layer_visual_revisions=lambda *args: None,
        )
        for has_area, has_layer, has_condition in (
            (True, False, False),
            (False, True, False),
            (True, True, True),
        ):
            for deferred in (False, True):
                for local in (False, True):
                    with self.subTest(
                        area=has_area,
                        layer=has_layer,
                        condition=has_condition,
                        deferred=deferred,
                        local=local,
                    ):
                        for counts in (
                            quantities,
                            summaries,
                            scans,
                            page_scans,
                            layer_loads,
                            rebuilds,
                            area_loads,
                        ):
                            counts.clear()
                        coordinator.takeoff_sidebar.calls.clear()
                        coordinator._page_settings_bar.calls.clear()
                        widget.load_conditions(conditions, {}, "Bid")
                        if has_condition:
                            coordinator._on_conditions_changed(
                                database_id=database_id,
                                bid_uid=bid_uid,
                                condition_uids=["c1"],
                                changed_fields=["layer_uid"],
                                change_operations=["update"],
                                defer_plan_projection=deferred,
                            )
                        if has_area:
                            coordinator._on_remote_areas_changed(
                                database_id=database_id,
                                bid_uid=bid_uid,
                                takeoff_family_pending=True,
                                summary_refresh_required=False,
                                defer_plan_projection=deferred,
                                local_completion=local,
                            )
                        coordinator._on_remote_bid_content_changed(
                            database_id=database_id,
                            bid_uid=bid_uid,
                            families=["takeoffs"] + (["layers"] if has_layer else []),
                            affected_page_uids_by_family={
                                "takeoffs": ["page-1", "page-2"]
                            },
                            condition_family_projected=has_condition,
                            area_family_projected=has_area,
                            defer_plan_projection=deferred,
                            local_completion=local,
                        )
                        self.assertEqual(widget._condition_items["c1"].text(2), "2")
                        self.assertEqual(summaries[-1].children[0].values.quantity1, 2)
                        self.assertEqual(
                            coordinator._page_settings_bar.calls[-1],
                            ({"area-new"}, {"area-new"}),
                        )
                        self.assertEqual(
                            (
                                len(quantities),
                                len(summaries),
                                len(scans),
                                len(page_scans),
                            ),
                            (1, 1, 1, 2),
                        )
                        self.assertEqual(len(layer_loads), int(has_layer))
                        self.assertEqual(len(rebuilds), int(has_condition or has_layer))

    def test_mixed_condition_takeoff_projection_calculates_final_aggregates_once(self):
        database_id = "sql-db"
        bid_uid = "bid-1"

        class SelectedUiState(FakeUiState):
            def get_selected_bid_ref(self):
                return BidRef(database_id, bid_uid)

        coordinator = UIEventCoordinator.__new__(UIEventCoordinator)
        coordinator.ui_state_manager = SelectedUiState()
        coordinator.project_data = FakeProjectData()
        coordinator.takeoff_sidebar = FakeTakeoffSidebar()
        coordinator._page_settings_bar = FakePageSettingsBar()
        coordinator._viewer = FakeViewer()
        coordinator._sidebar = FakeSidebar()
        coordinator._toolbar = FakeToolbar()
        coordinator.main_window = FakeMainWindow()
        coordinator.plan_view = SimpleNamespace(
            has_active_remote_projection_blocker=lambda: False
        )
        coordinator._plan_view_handler = None
        coordinator._is_cleaning_up = False
        coordinator._undo_service = None
        coordinator._selected_takeoff_uids = ()
        coordinator._pending_hotlink_page_uid = None
        coordinator._pending_hotlink_named_view = None
        coordinator._restore_project_tree_bid_selection_if_needed = lambda: None
        configure_mesh_state(coordinator, view_index=0)
        self.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
        from ost_visualizer.application.dtos.condition_summary_dtos import (
            ConditionSummaryGrouping,
        )
        from ost_visualizer.application.use_cases.project.condition_summary_service import (
            ConditionSummaryService,
        )
        from ost_visualizer.domain.entities.bid import Bid
        from ost_visualizer.domain.services.condition_quantity_service import (
            compute_page_quantities,
        )
        from ost_visualizer.presentation.components.conditions_sidebar import (
            ConditionsSidebar,
        )
        from ost_visualizer.presentation.coordinators.sidebar_coordinator import (
            SidebarCoordinator,
        )

        widget = ConditionsSidebar(None)
        self.addCleanup(lambda: delete(widget))
        conditions = {
            "c1": Condition("c1", name="Updated", condition_type=2, calc_type1=23)
        }
        takeoffs = [
            Takeoff("t1", "c1", "page-1", position=[0, 0]),
            Takeoff("t2", "c1", "page-2", position=[10, 10]),
        ]
        quantities = []
        summaries = []

        def calculate(pages, only_condition_uids=None):
            quantities.append(tuple(pages))
            return compute_page_quantities(
                conditions,
                [t for t in takeoffs if t.page_uid in pages],
                only_condition_uids,
            )

        data = coordinator.project_data
        data.selected_page_uids = ["page-1", "page-2"]
        data.compute_quantities_for_pages = calculate
        data.has_takeoffs_for_pages = lambda pages: any(
            t.page_uid in pages for t in takeoffs
        )
        data.get_bid_conditions = lambda: conditions
        data.get_bid_condition_folders = lambda: {}
        data.get_bid = lambda ref: Bid("bid-1", "Bid")
        data.get_bid_layer_snapshot = lambda: []
        data.get_cdn_types = lambda: {}
        data.get_all_takeoffs = lambda: takeoffs
        data.get_all_pages = lambda: [Page("page-1", "First"), Page("page-2", "Second")]
        data.get_bid_area_snapshot = lambda: []
        state = coordinator.ui_state_manager
        state.highlighted_condition_uids = set()
        state.set_highlighted_conditions = lambda uids: None
        state.state = SimpleNamespace(grayscale_enabled=False)
        sidebar = SidebarCoordinator.__new__(SidebarCoordinator)
        sidebar.conditions_sidebar = widget
        sidebar._project_data = data
        sidebar._ui_state = state
        sidebar._view_stack = coordinator._view_stack
        sidebar._condition_summary_service = ConditionSummaryService()
        sidebar.condition_summary_tab = SimpleNamespace(
            grouping=ConditionSummaryGrouping(),
            load_summary=lambda root, *args: summaries.append(root),
        )
        coordinator._sidebar = sidebar
        coordinator._reconcile_active_placement = lambda **_kwargs: None
        coordinator._restore_sidebar_highlight = lambda *args, **kwargs: None
        coordinator._is_summary_tab_active = lambda: True
        coordinator._load_condition_summary = sidebar.load_condition_summary_from_memory
        coordinator._on_conditions_changed(
            database_id=database_id,
            bid_uid=bid_uid,
            condition_uids=["c1"],
            changed_fields=["condition_type"],
            change_operations=["update"],
            defer_plan_projection=True,
        )
        coordinator._on_remote_bid_content_changed(
            database_id=database_id,
            bid_uid=bid_uid,
            families=["takeoffs"],
            condition_family_projected=True,
            affected_page_uids_by_family={"takeoffs": ["page-1", "page-2"]},
            defer_plan_projection=True,
        )
        barrier = RemoteProjectionBarrier(
            database_id=database_id,
            runtime_generation=3,
            is_runtime_current=lambda *args: True,
            on_complete=lambda success: None,
        )
        coordinator._on_remote_plan_projection_requested(
            database_id=database_id,
            bid_uid=bid_uid,
            runtime_generation=3,
            families=("takeoffs",),
            condition_uids=("c1",),
            condition_changed_fields=("condition_type",),
            condition_change_operations=("update",),
            areas_changed=False,
            resource_uids_by_family={},
            barrier=barrier,
        )
        barrier.seal()
        self.assertEqual(widget._condition_items["c1"].text(2), "2")
        self.assertEqual(summaries[-1].children[0].values.quantity1, 2)
        self.assertEqual(
            coordinator.takeoff_sidebar.calls, [("page-1", True), ("page-2", True)]
        )
        self.assertEqual((len(quantities), len(summaries)), (1, 1))
        # Immediate local replay and remote projection consume the same final data.
        for field in ("condition_type", "folder_uid", "layer_uid"):
            for local_completion in (False, True):
                with self.subTest(field=field, local_completion=local_completion):
                    quantities.clear()
                    summaries.clear()
                    takeoffs[:] = [Takeoff("t3", "c1", "page-2", position=[5, 5])]
                    coordinator._on_conditions_changed(
                        database_id=database_id,
                        bid_uid=bid_uid,
                        condition_uids=["c1"],
                        changed_fields=[field],
                        change_operations=["update"],
                    )
                    coordinator._on_remote_bid_content_changed(
                        database_id=database_id,
                        bid_uid=bid_uid,
                        families=["takeoffs"],
                        affected_page_uids_by_family={"takeoffs": ["page-1", "page-2"]},
                        condition_family_projected=True,
                        local_completion=local_completion,
                    )
                    self.assertEqual(widget._condition_items["c1"].text(2), "1")
                    self.assertEqual(summaries[-1].children[0].values.quantity1, 1)
                    self.assertEqual((len(quantities), len(summaries)), (1, 1))

    def test_remote_other_page_takeoff_refresh_updates_visible_3d_quantities(self):
        self.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
        database_id = "sql-db"
        bid_uid = "bid-1"

        class SelectedUiState(FakeUiState):
            def get_selected_bid_ref(self):
                return BidRef(database_id, bid_uid)

        coordinator = UIEventCoordinator.__new__(UIEventCoordinator)
        coordinator.ui_state_manager = SelectedUiState()
        coordinator.project_data = FakeProjectData()
        coordinator.takeoff_sidebar = FakeTakeoffSidebar()
        coordinator._page_settings_bar = FakePageSettingsBar()
        coordinator._viewer = FakeViewer()
        coordinator._sidebar = FakeSidebar()
        coordinator._toolbar = FakeToolbar()
        coordinator.main_window = FakeMainWindow()
        coordinator.plan_view = SimpleNamespace(
            has_active_remote_projection_blocker=lambda: False
        )
        coordinator._plan_view_handler = None
        coordinator._is_cleaning_up = False
        coordinator._undo_service = None
        coordinator._selected_takeoff_uids = ()
        coordinator._pending_hotlink_page_uid = None
        coordinator._pending_hotlink_named_view = None
        coordinator._restore_project_tree_bid_selection_if_needed = lambda: None
        configure_mesh_state(coordinator, view_index=0)
        from ost_visualizer.domain.services.condition_quantity_service import (
            compute_page_quantities,
        )
        from ost_visualizer.presentation.components.conditions_sidebar import (
            ConditionsSidebar,
        )
        from ost_visualizer.presentation.coordinators.sidebar_coordinator import (
            SidebarCoordinator,
        )

        widget = ConditionsSidebar(None)
        self.addCleanup(lambda: delete(widget))
        conditions = {
            "c1": Condition("c1", name="Count", condition_type=2, calc_type1=23)
        }
        widget.load_conditions(conditions, {}, "Bid")
        takeoffs = [Takeoff("t1", "c1", "page-1", position=[0, 0])]
        coordinator.project_data.selected_page_uids = ["page-1", "page-2"]
        from ost_visualizer.domain.entities.bid import Bid
        from ost_visualizer.presentation.components.page_combo import (
            _ITEM_ROLE_PRECHECK_ICON,
            PageComboBox,
        )

        pages = PageComboBox()
        self.addCleanup(lambda: delete(pages))
        pages.load_bid(
            Bid(
                "bid-1",
                "Bid",
                pages_without_folder=[
                    Page("page-1", "First"),
                    Page("page-2", "Second"),
                ],
            ),
            {"page-1"},
        )
        coordinator.takeoff_sidebar.set_page_has_takeoffs = pages.set_page_has_takeoffs
        coordinator.project_data.has_takeoffs_for_pages = lambda uids: any(
            t.page_uid in uids for t in takeoffs
        )
        indicator = pages._page_items["page-2"]
        inactive_icon = indicator.data(_ITEM_ROLE_PRECHECK_ICON).cacheKey()
        coordinator.project_data.compute_quantities_for_pages = (
            lambda pages, only_condition_uids=None: compute_page_quantities(
                conditions,
                [t for t in takeoffs if t.page_uid in pages],
                only_condition_uids,
            )
        )
        sidebar = SidebarCoordinator.__new__(SidebarCoordinator)
        sidebar.conditions_sidebar = widget
        sidebar._project_data = coordinator.project_data
        sidebar._ui_state = coordinator.ui_state_manager
        sidebar._view_stack = coordinator._view_stack
        coordinator._sidebar.update_conditions_quantities = (
            sidebar.update_conditions_quantities
        )
        sidebar.update_conditions_quantities()
        row = widget._condition_items["c1"]
        before = row.text(2)
        takeoffs.append(Takeoff("t2", "c1", "page-2", position=[10, 10]))
        completed = []
        barrier = RemoteProjectionBarrier(
            database_id=database_id,
            runtime_generation=3,
            is_runtime_current=lambda _database_id, _generation: True,
            on_complete=completed.append,
        )
        coordinator._on_remote_bid_content_changed(
            database_id=database_id,
            bid_uid=bid_uid,
            families=[CollaborationResourceFamily.TAKEOFFS.value],
            resource_uids_by_family={
                CollaborationResourceFamily.TAKEOFFS.value: ["takeoff-1"]
            },
            affected_page_uids_by_family={
                CollaborationResourceFamily.TAKEOFFS.value: ["page-2"]
            },
            defer_plan_projection=True,
        )
        self.assertEqual(coordinator._viewer.plan_pages, [])
        self.assertEqual(coordinator.visualization_service.mesh_pages, [])
        coordinator._on_remote_plan_projection_requested(
            database_id=database_id,
            bid_uid=bid_uid,
            runtime_generation=3,
            families=(CollaborationResourceFamily.TAKEOFFS.value,),
            condition_uids=(),
            condition_changed_fields=None,
            condition_change_operations=(),
            areas_changed=False,
            resource_uids_by_family={
                CollaborationResourceFamily.TAKEOFFS.value: ("takeoff-1",)
            },
            affected_page_uids_by_family={
                CollaborationResourceFamily.TAKEOFFS.value: ("page-2",)
            },
            barrier=barrier,
        )
        barrier.seal()
        self.assertEqual(len(coordinator._viewer.remote_requests), 0)
        self.assertEqual(
            coordinator.visualization_service.mesh_pages, [["page-1", "page-2"]]
        )
        self.assertEqual(completed, [True])
        self.assertNotEqual(
            indicator.data(_ITEM_ROLE_PRECHECK_ICON).cacheKey(), inactive_icon
        )
        self.assertEqual(before, "1")
        self.assertEqual(row.text(2), "2")
        projected = row.text(2)
        sidebar.update_conditions_quantities()
        self.assertEqual(row.text(2), projected)
        # Local deletion/undo-style recovery and remote projection converge.
        removed = takeoffs.pop()
        coordinator._on_takeoffs_changed(
            page_uid="page-2", update_mesh=False, update_shell=False
        )
        self.assertEqual(
            indicator.data(_ITEM_ROLE_PRECHECK_ICON).cacheKey(), inactive_icon
        )
        self.assertEqual(row.text(2), "1")
        takeoffs.append(removed)
        coordinator._on_remote_bid_content_changed(
            database_id=database_id,
            bid_uid=bid_uid,
            families=[CollaborationResourceFamily.TAKEOFFS.value],
            affected_page_uids_by_family={
                CollaborationResourceFamily.TAKEOFFS.value: ["page-2"]
            },
            defer_plan_projection=True,
        )
        self.assertEqual(row.text(2), "2")
        self.assertNotEqual(
            indicator.data(_ITEM_ROLE_PRECHECK_ICON).cacheKey(), inactive_icon
        )
        takeoffs.pop()
        coordinator._on_remote_bid_content_changed(
            database_id=database_id,
            bid_uid=bid_uid,
            families=[CollaborationResourceFamily.TAKEOFFS.value],
            affected_page_uids_by_family={
                CollaborationResourceFamily.TAKEOFFS.value: ["page-2"]
            },
            defer_plan_projection=True,
        )
        self.assertEqual(
            indicator.data(_ITEM_ROLE_PRECHECK_ICON).cacheKey(), inactive_icon
        )
        self.assertEqual(row.text(2), "1")
        takeoffs.append(removed)
        widget.load_conditions(conditions, {}, "Bid")
        sidebar.update_conditions_quantities()
        self.assertEqual(widget._condition_items["c1"].text(2), "2")
