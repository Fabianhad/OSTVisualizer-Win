import logging
import os
import unittest
import uuid
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from ost_visualizer.application.dtos.collaboration_dtos import (
    CollaborationShutdownState,
    DatabaseMutationResult,
    MutationOutcomeStatus,
    QueuedMutationResult,
)
from ost_visualizer.application.services.project_write_service import (
    ProjectWriteService,
    WriteReloadResult,
)
from ost_visualizer.domain.entities.condition import Condition
from ost_visualizer.domain.entities.identity_refs import BidRef
from ost_visualizer.domain.entities.layer import BidLayer
from ost_visualizer.domain.entities.page import Page
from ost_visualizer.presentation.components.layers_sidebar import BidLayersSidebar
from ost_visualizer.presentation.config import TAB_INDEX_TAKEOFF
from ost_visualizer.presentation.coordinators.ui_event_coordinator import (
    UIEventCoordinator,
)
from ost_visualizer.presentation.managers.deferred_persistence_manager import (
    DeferredPersistenceManager,
)
from PySide6 import QtCore, QtWidgets
from tests.presentation.managers.deferred_persistence_support import (
    FakeIndexWidget,
    FakeProjectWriteService,
    FakeSqlWorkspaceService,
    RecordingDeferredPersistence,
    RecordingPlanView,
    _workspace_service,
)


class DeferredLayerVisibilityWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def _install_hidden_2d_mesh_state(self, coordinator):
        mesh_refresh_calls = []
        coordinator._tab_widget = FakeIndexWidget(TAB_INDEX_TAKEOFF)
        coordinator._view_stack = FakeIndexWidget(1)
        coordinator._mesh_window = None
        coordinator.opengl_viewer = None
        coordinator._mesh_scene_dirty = False
        coordinator._dirty_mesh_page_uids = set()
        coordinator._pending_dirty_mesh_refresh = False
        coordinator._last_mesh_scene = None
        coordinator.visualization_service = SimpleNamespace(
            refresh_mesh_view=lambda page_uids: mesh_refresh_calls.append(
                list(page_uids)
            )
        )
        coordinator.mesh_refresh_calls = mesh_refresh_calls
        return mesh_refresh_calls

    def _make_visibility_coordinator(
        self,
        *,
        layer_name="Layer 1",
        selected_page_uids=None,
        active_page_uid="p1",
        condition_layer_uid="l1",
        page_layer_uid=None,
    ):
        selected_page_uids = selected_page_uids or [active_page_uid]
        page_layer_uid = (
            "l1" if page_layer_uid is None and layer_name == "Image" else page_layer_uid
        )
        coordinator = UIEventCoordinator.__new__(UIEventCoordinator)
        coordinator._is_cleaning_up = False
        coordinator._project_write_service = SimpleNamespace(
            uses_sql_collaboration_mutations=lambda _file_path: False
        )
        coordinator.ui_access_manager = SimpleNamespace(
            is_allowed=lambda _feature: True
        )
        coordinator.ui_state_manager = SimpleNamespace(
            get_selected_bid_ref=lambda: BidRef("a.mdb", "bid-1"),
            active_page_uid=active_page_uid,
            place_condition_uid=None,
            place_condition_uids=[],
            state=SimpleNamespace(grayscale_enabled=False),
        )
        pages = {
            "p1": Page(uid="p1", name="P1"),
            "p2": Page(uid="p2", name="P2"),
        }
        conditions = {
            "c1": Condition(uid="c1", name="C1", layer_uid=condition_layer_uid),
        }
        layers = [
            SimpleNamespace(uid="l1", name=layer_name, show=True),
            SimpleNamespace(uid="other", name="Other", show=True),
            SimpleNamespace(uid="annotation-layer", name="Annotation", show=True),
        ]
        annotation_layer_uid = "annotation-layer"
        bid_owner = object()
        coordinator.quantity_update_calls = []
        quantity_calls = coordinator.quantity_update_calls

        def is_page_layer_uid(layer_uid):
            return page_layer_uid is not None and str(layer_uid) == str(page_layer_uid)

        def update_layer_visibility(layer_uid, show):
            for layer in layers:
                if str(layer.uid) == str(layer_uid):
                    layer.show = bool(show)
            if not is_page_layer_uid(layer_uid):
                return []
            for page in pages.values():
                page.layer_visible = bool(show)
            return ["p1", "p2"]

        def update_all_layer_visibility(show):
            for page in pages.values():
                page.layer_visible = bool(show)
            return ["p1", "p2"]

        coordinator.project_data = SimpleNamespace(
            is_image_layer_uid=is_page_layer_uid,
            update_layer_visibility=update_layer_visibility,
            update_all_layer_visibility=update_all_layer_visibility,
            set_bid_layer_visibility=lambda _layers: None,
            get_hidden_layer_uids=lambda: set(),
            is_annotation_layer_visible=lambda: True,
            get_selected_page_uids=lambda: list(selected_page_uids),
            get_bid=lambda _bid_ref: bid_owner,
            get_page=lambda page_uid: pages.get(page_uid),
            get_bid_layer_snapshot=lambda: list(layers),
            get_bid_conditions=lambda: conditions,
            get_annotation_layer_uid=lambda: annotation_layer_uid,
        )
        coordinator._project_read_service = SimpleNamespace(
            get_merged_bid_layers=lambda _db_path, _bid_uid: list(layers)
        )
        coordinator._sidebar = SimpleNamespace(
            bid_layers_sidebar=SimpleNamespace(
                get_layer=lambda _uid: layers[0],
                get_layers=lambda: list(layers),
                get_layer_visibility=lambda layer_uid: next(
                    (
                        bool(layer.show)
                        for layer in layers
                        if str(layer.uid) == str(layer_uid)
                    ),
                    None,
                ),
                set_layer_visible=lambda layer_uid, show: [
                    setattr(layer, "show", bool(show))
                    for layer in layers
                    if str(layer.uid) == str(layer_uid)
                ],
                set_all_layers_visible=lambda show: [
                    setattr(layer, "show", bool(show)) for layer in layers
                ],
            ),
            update_conditions_quantities=lambda: quantity_calls.append("quantity"),
            load_condition_summary=lambda: None,
        )
        coordinator.conditions_sidebar = None
        coordinator.condition_summary_tab = None
        coordinator.layer_events = []
        coordinator.event_bus = SimpleNamespace(
            publish=lambda event, **event_payload: coordinator.layer_events.append(
                (event, event_payload)
            )
        )
        coordinator._viewer = SimpleNamespace(update_viewers=lambda page_uids: None)
        coordinator._update_plan_view_calls = []
        coordinator._update_plan_view = (
            lambda page_uid: coordinator._update_plan_view_calls.append(page_uid)
        )
        coordinator._update_export_menu_state = lambda: None
        coordinator.ui_access_manager = SimpleNamespace(
            is_allowed=lambda _feature: True
        )

        def enter_place(condition_uid, _selected):
            coordinator.plan_view.cursor_mode = "place"
            coordinator.plan_view.place_condition_uid = condition_uid
            coordinator.ui_state_manager.place_condition_uid = condition_uid
            coordinator.ui_state_manager.place_condition_uids = list(_selected)
            return True

        coordinator._placement = SimpleNamespace(enter=enter_place)
        coordinator.select_checked_calls = []
        coordinator.toolbar_refresh_calls = []
        coordinator._toolbar = SimpleNamespace(
            refresh=lambda: coordinator.toolbar_refresh_calls.append("refresh"),
            set_select_checked=lambda: coordinator.select_checked_calls.append(
                "select"
            ),
            is_takeoff_2d_view_active=lambda: True,
        )
        coordinator._suspended_layer_tool = None
        coordinator.plan_view = RecordingPlanView()
        coordinator._deferred_persistence = RecordingDeferredPersistence()
        coordinator._visibility_test_layers = layers
        self._install_hidden_2d_mesh_state(coordinator)
        return coordinator

    def test_layer_sidebar_bulk_visibility_failure_and_retry_projection(self):
        for sql in (False, True):
            for requested in (False, True):
                with self.subTest(sql=sql, requested=requested):
                    coordinator = self._make_visibility_coordinator()
                    layers = coordinator._visibility_test_layers
                    layers[:] = [
                        BidLayer("l1", "bid-1", "Layer 1", True, 1),
                        BidLayer("other", "bid-1", "Other", False, 2),
                    ]
                    original = [layer.show for layer in layers]
                    for page_uid in ("p1", "p2"):
                        coordinator.project_data.get_page(page_uid).layer_visible = (
                            not requested
                        )
                    sidebar = BidLayersSidebar(None)
                    sidebar.load_layers(layers)
                    sidebar.layers_show_all.connect(coordinator._on_layers_show_all)
                    coordinator._sidebar.bid_layers_sidebar = sidebar
                    coordinator._sidebar.load_condition_summary_from_memory = (
                        lambda: None
                    )
                    coordinator._project_write_service.uses_sql_collaboration_mutations = (
                        lambda _path: sql
                    )
                    service = FakeProjectWriteService()
                    service.queue_sql_settings = sql
                    service.fail_methods.add("update_all_layers_show")
                    manager = DeferredPersistenceManager(
                        service, _workspace_service(service)
                    )
                    coordinator._deferred_persistence = manager
                    try:
                        button = (
                            sidebar._select_all_btn
                            if requested
                            else sidebar._unselect_all_btn
                        )
                        button.click()
                        self.assertEqual(
                            [box.isChecked() for box in sidebar._checkboxes],
                            [requested, requested],
                        )
                        # The optimistic projection reaches the loaded pages.
                        self.assertEqual(
                            [
                                coordinator.project_data.get_page(uid).layer_visible
                                for uid in ("p1", "p2")
                            ],
                            [requested, requested],
                        )
                        self.assertEqual(manager.flush(), sql)
                        if sql:
                            self.assertEqual(len(service.queued_setting_callbacks), 1)
                            service.queued_setting_callbacks[0](
                                QueuedMutationResult(
                                    database_id="a.mdb",
                                    runtime_generation=1,
                                    operation_id=str(uuid.uuid4()),
                                    outcome_status=MutationOutcomeStatus.REJECTED,
                                )
                            )
                            expected = original
                        else:
                            # Access failure remains pending, but its optimistic
                            # projection is rolled back until a retry succeeds.
                            self.assertEqual(manager.pending_count, 1)
                            self.assertEqual(
                                [box.isChecked() for box in sidebar._checkboxes],
                                original,
                            )
                            service.fail_methods.clear()
                            self.assertTrue(manager.flush())
                            expected = [requested, requested]
                        self.assertEqual(
                            [box.isChecked() for box in sidebar._checkboxes], expected
                        )
                        self.assertEqual([layer.show for layer in layers], expected)
                        self.assertEqual(manager.pending_count, 0)
                    finally:
                        manager.cancel_for_file("a.mdb")
                        manager.cleanup()
                        sidebar.close()
                        sidebar.deleteLater()

    def test_noop_bulk_intent_supersedes_rolled_back_mdb_retry(self):
        coordinator = self._make_visibility_coordinator()
        layers = coordinator._visibility_test_layers
        layers[:] = [
            BidLayer("l1", "bid-1", "Layer 1", False, 1),
            BidLayer("other", "bid-1", "Other", False, 2),
        ]
        sidebar = BidLayersSidebar(None)
        sidebar.load_layers(layers)
        sidebar.layers_show_all.connect(coordinator._on_layers_show_all)
        coordinator._sidebar.bid_layers_sidebar = sidebar
        coordinator._sidebar.load_condition_summary_from_memory = lambda: None
        service = FakeProjectWriteService()
        service.fail_methods.add("update_all_layers_show")
        manager = DeferredPersistenceManager(service, _workspace_service(service))
        coordinator._deferred_persistence = manager
        try:
            sidebar._select_all_btn.click()
            self.assertFalse(manager.flush())
            self.assertEqual([layer.show for layer in layers], [False, False])
            self.assertEqual(manager.pending_count, 1)
            sidebar._unselect_all_btn.click()
            service.fail_methods.clear()
            self.assertTrue(manager.flush())
            self.assertEqual([layer.show for layer in layers], [False, False])
            self.assertEqual(
                [call[3] for call in service.calls if call[0] == "all_layers_show"],
                [True, False],
            )
            self.assertEqual(manager.pending_count, 0)
        finally:
            manager.cancel_for_file("a.mdb")
            manager.cleanup()
            sidebar.close()
            sidebar.deleteLater()

    def test_noop_bulk_intent_supersedes_rolled_back_individual_retry(self):
        coordinator = self._make_visibility_coordinator()
        layers = coordinator._visibility_test_layers
        layers[:] = [
            BidLayer("l1", "bid-1", "Layer 1", False, 1),
            BidLayer("other", "bid-1", "Other", False, 2),
        ]
        sidebar = BidLayersSidebar(None)
        sidebar.load_layers(layers)
        sidebar.set_toggle_callback(coordinator.update_layer_visibility_deferred)
        sidebar.layers_show_all.connect(coordinator._on_layers_show_all)
        coordinator._sidebar.bid_layers_sidebar = sidebar
        coordinator._sidebar.load_condition_summary_from_memory = lambda: None
        service = FakeProjectWriteService()
        service.fail_methods.add("update_layer_show")
        manager = DeferredPersistenceManager(service, _workspace_service(service))
        coordinator._deferred_persistence = manager
        try:
            sidebar._checkboxes[0].click()
            self.assertFalse(manager.flush())
            self.assertEqual([layer.show for layer in layers], [False, False])
            self.assertEqual(manager.pending_count, 1)
            sidebar._unselect_all_btn.click()
            service.fail_methods.clear()
            self.assertTrue(manager.flush())
            self.assertEqual([layer.show for layer in layers], [False, False])
            self.assertEqual(
                [call[0] for call in service.calls],
                ["layer_show", "all_layers_show"],
            )
            self.assertEqual(manager.pending_count, 0)
        finally:
            manager.cancel_for_file("a.mdb")
            manager.cleanup()
            sidebar.close()
            sidebar.deleteLater()

    def test_repeated_layer_toggles_coalesce_to_last_write(self):
        service = FakeProjectWriteService()
        manager = DeferredPersistenceManager(
            service,
            _workspace_service(service),
            logger_=logging.getLogger(__name__),
        )
        self.addCleanup(manager.cleanup)
        manager.schedule_layer_show("a.mdb", "l1", False)
        manager.schedule_layer_show("a.mdb", "l1", True)
        self.assertEqual(manager.pending_count, 1)
        self.assertTrue(manager.flush())
        self.assertEqual(
            service.calls,
            [("layer_show", "a.mdb", "l1", True, False)],
        )

    def _connected_sidebar(self, coordinator, layers):
        sidebar = BidLayersSidebar(None)
        sidebar.load_layers(layers)
        sidebar.set_toggle_callback(coordinator.update_layer_visibility_deferred)
        sidebar.layers_show_all.connect(coordinator._on_layers_show_all)
        coordinator._sidebar.bid_layers_sidebar = sidebar
        coordinator._sidebar.load_condition_summary_from_memory = lambda: None
        service = FakeProjectWriteService()
        manager = DeferredPersistenceManager(service, _workspace_service(service))
        coordinator._deferred_persistence = manager
        return sidebar, service, manager

    def test_failed_retry_of_one_layer_survives_a_toggle_of_another_layer(self):
        coordinator = self._make_visibility_coordinator()
        layers = coordinator._visibility_test_layers
        layers[:] = [
            BidLayer("l1", "bid-1", "Layer 1", True, 1),
            BidLayer("other", "bid-1", "Other", True, 2),
        ]
        sidebar, service, manager = self._connected_sidebar(coordinator, layers)
        service.fail_methods.add("update_layer_show")
        try:
            sidebar._checkboxes[0].click()
            self.assertFalse(manager.flush())
            self.assertEqual(manager.pending_count, 1)
            sidebar._checkboxes[1].click()
            # The failed retry of l1 is not superseded by an unrelated layer.
            self.assertEqual(manager.pending_count, 2)
            service.fail_methods.clear()
            self.assertTrue(manager.flush())
            self.assertEqual(manager.pending_count, 0)
            self.assertEqual(
                [call[2] for call in service.calls if call[0] == "layer_show"],
                ["l1", "l1", "other"],
            )
            self.assertEqual([layer.show for layer in layers], [False, False])
        finally:
            manager.cancel_for_file("a.mdb")
            manager.cleanup()
            sidebar.close()
            sidebar.deleteLater()

    def test_unattempted_layer_write_is_not_discarded_by_a_later_bulk_intent(self):
        coordinator = self._make_visibility_coordinator()
        layers = coordinator._visibility_test_layers
        layers[:] = [
            BidLayer("l1", "bid-1", "Layer 1", True, 1),
            BidLayer("other", "bid-1", "Other", False, 2),
        ]
        sidebar, service, manager = self._connected_sidebar(coordinator, layers)
        try:
            sidebar._checkboxes[0].click()
            sidebar._select_all_btn.click()
            self.assertEqual(manager.pending_count, 2)
            self.assertTrue(manager.flush())
            # Only a write that already failed is superseded; this one never ran
            # although the bulk intent covers the same layer.
            self.assertEqual(
                [(call[0], call[3]) for call in service.calls],
                [("layer_show", False), ("all_layers_show", True)],
            )
            self.assertEqual([layer.show for layer in layers], [True, True])
            self.assertEqual(manager.pending_count, 0)
        finally:
            manager.cancel_for_file("a.mdb")
            manager.cleanup()
            sidebar.close()
            sidebar.deleteLater()
