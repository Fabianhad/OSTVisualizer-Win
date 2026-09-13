import os
import sys
import unittest
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6 import QtWidgets
from shiboken6 import delete, isValid
from ost_visualizer.domain.aggregates.ost_aggregate import OstAggregate
from ost_visualizer.application.dtos.remote_projection_dtos import (
    RemoteProjectionBarrier,
)
from ost_visualizer.domain.entities.annotation import (
    BidAnnotation,
    ANNOTATION_TYPE_TEXT,
)
from ost_visualizer.domain.entities.bid import Bid
from ost_visualizer.domain.entities.hierarchy_data import (
    HierarchyData,
    HierarchyFileEntry,
    HierarchyBidInfo,
    HierarchyPageInfo,
)
from ost_visualizer.domain.entities.condition import Condition
from ost_visualizer.domain.entities.identity_refs import BidRef
from ost_visualizer.domain.entities.page import Page
from ost_visualizer.domain.entities.takeoff import Takeoff
from ost_visualizer.domain.services.project_data_service import ProjectDataService
from ost_visualizer.presentation.components import conditions_sidebar as sidebar_module
from ost_visualizer.presentation.components.conditions_sidebar import ConditionsSidebar
from ost_visualizer.presentation.components.plan_view.view import TakeoffPlanView
from ost_visualizer.presentation.config import TAB_INDEX_TAKEOFF
from ost_visualizer.presentation.coordinators.ui_event_coordinator import (
    UIEventCoordinator,
)
from ost_visualizer.presentation.coordinators.viewer_sync_coordinator import (
    ViewerSyncCoordinator,
)
from tests.test_remote_plan_update_pipeline import _ManualThreadPool, _QueuedBridge
from ost_visualizer.presentation.managers.ui_access_manager import (
    MAIN_PLAN_SURFACE_ID,
    PlanSurfaceAccessState,
)
from tests.test_viewer_sync_coordinator_overlay_refresh import (
    FakeAnnotationRenderer,
    FakeColorService,
    FakeLinearGeometry,
    FakeLoadCoordinator,
    FakeRenderingService,
    RecordingPathTakeoffRenderer,
)


class ConditionObjectSelectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def setUp(self):
        qt_errors = []
        self.addCleanup(lambda: self.assertEqual(qt_errors, []))
        exception_hook = patch.object(
            sys, "excepthook", side_effect=lambda *exc: qt_errors.append(exc)
        )
        exception_hook.start()
        self.addCleanup(exception_hook.stop)
        self.bid_ref = BidRef("C:/selection.mdb", "bid")
        self.conditions = {
            uid: Condition(
                uid=uid, name=uid, ref_no=index, condition_type=Condition.TYPE_LINEAR
            )
            for index, uid in enumerate(("target", "other", "unused", "elsewhere"), 1)
        }
        self.page = Page(
            uid="p1",
            name="Current",
            takeoffs=[
                self.takeoff("1", "target", "p1"),
                self.takeoff("2", "target", "p1"),
                self.takeoff("3", "other", "p1"),
            ],
        )
        self.other_page = Page(
            uid="p2",
            name="Other",
            takeoffs=[
                self.takeoff("4", "target", "p2"),
                self.takeoff("5", "elsewhere", "p2"),
            ],
        )
        self.model = OstAggregate(Mock())
        self.model.current_bid_ref = self.bid_ref
        self.model.current_bid = Bid(uid="bid", name="Bid")
        self.model.set_hierarchy(
            HierarchyData(
                loaded_files=[
                    HierarchyFileEntry(
                        file_path=self.bid_ref.file_path,
                        orphan_bids=[
                            HierarchyBidInfo(
                                uid=self.bid_ref.bid_uid,
                                name="Bid",
                                pages_without_folder=[
                                    HierarchyPageInfo(uid=p.uid, name=p.name)
                                    for p in (self.page, self.other_page)
                                ],
                            )
                        ],
                    )
                ]
            )
        )
        self.model.bid_conditions = self.conditions
        self.model.set_pages({"p1": self.page, "p2": self.other_page})
        self.data = ProjectDataService(self.model)
        self.plan = self.make_plan()
        self.load_page(self.plan, self.page)
        self.sidebar = ConditionsSidebar(None)
        self.addCleanup(lambda: delete(self.sidebar) if isValid(self.sidebar) else None)
        self.sidebar.load_conditions(self.conditions, {}, "Project")
        self.sidebar.resize(500, 400)
        self.sidebar.tree.expandAll()
        self.sidebar.show()
        self.app.processEvents()
        self.state = SimpleNamespace(
            active_page_uid="p1",
            highlighted_condition_uids=set(),
            get_selected_bid_ref=lambda: self.bid_ref,
        )

        def set_highlighted_conditions(uids):
            self.state.highlighted_condition_uids = set(uids)

        self.state.set_highlighted_conditions = set_highlighted_conditions
        self.access = Mock()
        self.access.get_plan_surface_access.return_value = PlanSurfaceAccessState(
            can_select_plan_items=True
        )
        self.coordinator = UIEventCoordinator.__new__(UIEventCoordinator)
        self.coordinator._is_cleaning_up = False
        self.coordinator.plan_view = self.plan
        self.coordinator.project_data = self.data
        self.coordinator.ui_state_manager = self.state
        self.coordinator.ui_access_manager = self.access
        self.coordinator.conditions_sidebar = self.sidebar
        self.coordinator._nav = SimpleNamespace(is_refreshing=False)
        self.coordinator._placement = SimpleNamespace(
            is_active=False, condition_uid=None
        )
        self.coordinator._toolbar = Mock()
        self.coordinator._toolbar.is_takeoff_2d_view_active.return_value = True
        self.coordinator._tab_widget = SimpleNamespace(
            currentIndex=lambda: TAB_INDEX_TAKEOFF
        )
        self.coordinator._selected_takeoff_uids = ()
        self.coordinator._selection_projected_condition_uids = set()
        self.coordinator.opengl_viewer = None
        self.coordinator._mesh_window = None
        project_view = Mock()
        project_view.get_selected_node_state.return_value = {
            "kind": "bid",
            "bid_uid": "bid",
            "file_path": self.bid_ref.file_path,
        }
        self.coordinator.main_window = SimpleNamespace(project_view=project_view)
        self.sidebar.set_select_objects_command_factory(
            self.coordinator.prepare_condition_object_selection
        )
        self.events = []
        self.plan.takeoff_selection_command_applied.connect(self.events.append)
        self.plan.takeoff_selection_changed.connect(
            self.coordinator._on_takeoff_selection_changed
        )
        self.plan.takeoff_selection_command_applied.connect(
            self.coordinator._on_takeoff_selection_command_applied
        )
        # Clear the Plan while its projection recipients still exist.
        self.addCleanup(lambda: self.plan.cleanup() if isValid(self.plan) else None)

    @staticmethod
    def takeoff(uid, condition_uid, page_uid):
        return Takeoff(
            uid=uid,
            condition_uid=condition_uid,
            page_uid=page_uid,
            position=[0.0, 0.0, 10.0, 10.0],
        )

    def make_plan(self):
        plan = TakeoffPlanView(
            color_service=FakeColorService(),
            rendering_service=FakeRenderingService(),
            load_coordinator=FakeLoadCoordinator(),
            takeoff_renderer=RecordingPathTakeoffRenderer(),
            annotation_renderer=FakeAnnotationRenderer(),
            linear_geometry=FakeLinearGeometry(),
        )
        self.addCleanup(lambda: delete(plan) if isValid(plan) else None)
        self.addCleanup(lambda: plan.cleanup() if isValid(plan) else None)
        plan.set_selection_enabled(True)
        return plan

    def load_page(self, plan, page, annotations=None):
        self.assertTrue(
            plan.load_page(
                page,
                page.takeoffs,
                self.conditions,
                {uid: "#000000" for uid in self.conditions},
                bid_ref=self.bid_ref,
                annotations=annotations,
            )
        )

    def open_menu(self, uid="target", during_menu=None):
        result = []

        def execute(menu, _position):
            action = next(a for a in menu.actions() if a.text() == "Select Objects")
            result.append(action.isEnabled())
            if during_menu:
                during_menu(action)

        item = self.sidebar._condition_items[uid]
        position = self.sidebar.tree.visualItemRect(item).center()
        with patch.object(sidebar_module, "exec_transient_menu", side_effect=execute):
            self.sidebar._on_context_menu(position)
        self.assertEqual(len(result), 1)
        return result[0]

    def test_enablement_uses_right_clicked_condition_and_displayed_page(self):
        self.assertTrue(self.open_menu("target"))
        self.assertFalse(self.open_menu("unused"))
        self.assertFalse(self.open_menu("elsewhere"))
        context = self.access.get_plan_surface_access.call_args.args[0]
        self.assertEqual(
            (context.surface_id, context.page_uid, context.bid_ref),
            (MAIN_PLAN_SURFACE_ID, "p1", self.bid_ref),
        )

    def test_inactive_main_plan_disables_and_invalidates_menu_selection(self):
        def invoke(action):
            self.coordinator._toolbar.is_takeoff_2d_view_active.return_value = False
            action.trigger()

        self.open_menu(during_menu=invoke)
        self.assertEqual(self.plan.get_selected_uids(), [])
        self.assertFalse(self.open_menu())

    def test_new_tool_intent_invalidates_menu_selection(self):
        def invoke(action):
            self.plan.set_cursor_mode("pan")
            action.trigger()

        self.open_menu(during_menu=invoke)
        self.assertEqual(self.plan.cursor_mode, "pan")
        self.assertEqual(self.plan.get_selected_uids(), [])

    def test_select_objects_after_accepted_remote_page_projection(self):
        bridge, pool = _QueuedBridge(), _ManualThreadPool()
        self.state.state = SimpleNamespace(
            display_mode_2d="condition", grayscale_enabled=False
        )
        self.state.place_condition_uids = []
        viewer = ViewerSyncCoordinator(
            self.state, self.access, FakeColorService(), self.data, bridge, pool
        )
        viewer.plan_view = self.plan
        self.addCleanup(viewer.cleanup)
        barrier = RemoteProjectionBarrier(
            database_id=self.bid_ref.file_path,
            runtime_generation=1,
            is_runtime_current=lambda _database, _generation: True,
            on_complete=lambda _success: None,
        )
        completed = []
        self.assertTrue(
            viewer.request_remote_plan_update(
                database_id=self.bid_ref.file_path,
                runtime_generation=1,
                bid_uid=self.bid_ref.bid_uid,
                resource_uids_by_family={},
                barrier=barrier,
                completion=completed.append,
            )
        )
        pool.run_next()
        callback, payload = bridge.callbacks.pop(0)
        callback(payload)
        self.assertEqual(completed, [True])
        self.assertTrue(self.open_menu(during_menu=lambda action: action.trigger()))
        self.assertEqual(self.plan.get_selected_uids(), ["1", "2"])

    def test_unprojected_takeoff_reassignment_cannot_select_old_condition_geometry(
        self,
    ):
        # Authoritative SQL hydration can precede the deferred Plan projection.
        self.page.takeoffs = [replace(self.page.takeoffs[-1], condition_uid="target")]
        enabled = self.open_menu(during_menu=lambda action: action.trigger())
        self.assertEqual(self.plan.get_selected_uids(), [])
        self.assertFalse(enabled)

    def test_selection_replaces_other_objects_and_uses_normal_highlighting(self):
        annotation = BidAnnotation(
            uid="1",
            page_uid="p1",
            annotation_type=ANNOTATION_TYPE_TEXT,
            position=[0.0, 0.0, 20.0, 20.0],
        )
        self.load_page(self.plan, self.page, [annotation])
        annotation_keys = self.plan.find_annotation_keys_by_uid_type(
            {("1", ANNOTATION_TYPE_TEXT)}
        )
        self.assertTrue(annotation_keys)
        self.plan.set_selected_uids({"3", *annotation_keys})
        self.open_menu(during_menu=lambda action: action.trigger())
        self.assertEqual(self.plan.get_selected_uids(), ["1", "2"])
        self.assertTrue(self.plan._selection_items)
        self.assertEqual(self.events[-1], ["1", "2"])
        self.assertEqual(self.sidebar.get_selected_condition_uids(), ["target"])
        self.coordinator._toolbar.refresh.assert_called()

    def test_right_click_does_not_use_later_current_or_multiselected_condition(self):
        self.sidebar.highlight_conditions({"target", "other"})

        def invoke(action):
            self.sidebar.highlight_conditions({"other"})
            action.trigger()

        self.open_menu(during_menu=invoke)
        self.assertEqual(self.plan.get_selected_takeoff_uids(), ["1", "2"])

    def test_unchanged_selection_reclaims_sidebar_projection(self):
        self.plan.set_selected_uids({"1", "2"})

        def invoke(action):
            self.sidebar.highlight_conditions({"other"})
            self.state.highlighted_condition_uids = {"other"}
            action.trigger()

        self.open_menu(during_menu=invoke)
        self.assertEqual(self.events, [["1", "2"]])
        self.assertEqual(self.sidebar.get_selected_condition_uids(), ["target"])

    def test_disappearing_matches_do_not_change_selection(self):
        self.plan.set_selected_uids({"3"})

        def invoke(action):
            self.page.takeoffs = [self.page.takeoffs[-1]]
            action.trigger()

        self.open_menu(during_menu=invoke)
        self.assertEqual(self.plan.get_selected_uids(), ["3"])
        self.assertEqual(self.events, [])

    def test_navigation_and_same_uid_page_replacement_reject_stale_action(self):
        for replacement in (self.other_page, replace(self.page)):
            with self.subTest(page=replacement.uid):
                self.model.set_pages({"p1": self.page, "p2": self.other_page})
                self.state.active_page_uid = "p1"
                self.load_page(self.plan, self.page)

                def invoke(action):
                    self.model.set_pages({replacement.uid: replacement})
                    self.state.active_page_uid = replacement.uid
                    self.load_page(self.plan, replacement)
                    action.trigger()

                self.open_menu(during_menu=invoke)
                self.assertEqual(self.plan.get_selected_uids(), [])
        self.assertEqual(self.events, [])

    def test_authoritative_replacement_before_plan_projection_rejects_action(self):
        def invoke(action):
            self.model.set_pages({"p1": replace(self.page)})
            action.trigger()

        self.open_menu(during_menu=invoke)
        self.assertEqual(self.events, [])

    def test_condition_replacement_deletion_and_tree_rebuild_reject_action(self):
        original = self.conditions["target"]
        for change in ("replace", "delete", "rebuild"):
            with self.subTest(change=change):
                self.conditions["target"] = original
                self.sidebar.load_conditions(self.conditions, {}, "Project")
                self.sidebar.tree.expandAll()

                def invoke(action):
                    if change == "delete":
                        self.conditions.pop("target")
                    else:
                        self.conditions["target"] = replace(original)
                    if change == "rebuild":
                        self.sidebar.load_conditions(self.conditions, {}, "Project")
                    action.trigger()

                self.open_menu(during_menu=invoke)
                self.assertEqual(self.events, [])

    def test_bid_replacement_rejects_action(self):
        def invoke(action):
            self.model.current_bid = replace(self.model.current_bid)
            action.trigger()

        self.open_menu(during_menu=invoke)
        self.assertEqual(self.events, [])

    def test_access_loss_disables_and_rejects_action(self):
        def invoke(action):
            self.access.get_plan_surface_access.return_value = PlanSurfaceAccessState()
            action.trigger()

        self.open_menu(during_menu=invoke)
        self.assertEqual(self.events, [])
        self.assertFalse(self.open_menu())

    def test_new_selection_intent_rejects_action(self):
        def invoke(action):
            self.plan.set_selected_uids({"3"})
            action.trigger()

        self.open_menu(during_menu=invoke)
        self.assertEqual(self.plan.get_selected_uids(), ["3"])
        self.assertEqual(self.events, [])

    def test_selection_change_and_restore_still_supersedes_menu(self):
        def invoke(action):
            self.plan.set_selected_uids({"3"})
            self.plan.clear_selection()
            action.trigger()

        self.open_menu(during_menu=invoke)
        self.assertEqual(self.plan.get_selected_uids(), [])
        self.assertEqual(self.events, [])

    def test_missing_or_not_yet_projected_page_disables_action(self):
        self.state.active_page_uid = "p2"
        self.assertFalse(self.open_menu())
        self.state.active_page_uid = "p1"
        self.plan.clear()
        self.assertFalse(self.open_menu())

    def test_command_enters_normal_selection_mode_from_pan(self):
        self.plan.set_cursor_mode("pan")
        self.open_menu(during_menu=lambda action: action.trigger())
        self.assertEqual(self.plan.cursor_mode, "select")
        self.assertEqual(self.plan.get_selected_uids(), ["1", "2"])

    def test_annotation_cannot_substitute_for_missing_rendered_takeoff(self):
        annotation = BidAnnotation(
            uid="1",
            page_uid="p1",
            annotation_type=ANNOTATION_TYPE_TEXT,
            position=[0.0, 0.0, 20.0, 20.0],
        )
        self.plan.load_page(
            self.page,
            [self.page.takeoffs[-1]],
            self.conditions,
            {uid: "#000000" for uid in self.conditions},
            bid_ref=self.bid_ref,
            annotations=[annotation],
        )
        self.plan.set_selected_uids({"3"})
        self.open_menu(during_menu=lambda action: action.trigger())
        self.assertEqual(self.plan.get_selected_uids(), ["3"])
        self.assertEqual(self.events, [])

    def test_destroyed_surface_and_cleanup_reject_action(self):
        def invoke(action):
            self.plan.cleanup()
            delete(self.plan)
            action.trigger()

        self.open_menu(during_menu=invoke)
        self.assertEqual(self.events, [])

    def test_main_condition_menu_leaves_another_plan_surface_unchanged(self):
        detached = self.make_plan()
        self.load_page(detached, self.other_page)
        detached.set_selected_uids({"5"})
        self.open_menu(during_menu=lambda action: action.trigger())
        self.assertEqual(self.plan.get_selected_uids(), ["1", "2"])
        self.assertEqual(detached.get_selected_uids(), ["5"])


if __name__ == "__main__":
    unittest.main()
