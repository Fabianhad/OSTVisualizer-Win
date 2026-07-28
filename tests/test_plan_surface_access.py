import unittest
from dataclasses import replace
from ost_visualizer.application.dtos.collaboration_dtos import ResourceRef
from ost_visualizer.application.events.app_events import AppEvents
from ost_visualizer.domain.entities.identity_refs import BidRef
from ost_visualizer.presentation.managers.ui_access_manager import (
    MAIN_PLAN_SURFACE_ID,
    PlanSurfaceAccessContext,
    PlanSurfaceAccessState,
    UIAccessManager,
)


class _EventBus:
    def __init__(self):
        self.subscribers = {}

    def subscribe(self, event_type, callback):
        self.subscribers.setdefault(event_type, []).append(callback)

    def unsubscribe(self, event_type, callback):
        self.subscribers[event_type].remove(callback)

    def publish(self, event_type, **kwargs):
        for callback in list(self.subscribers.get(event_type, ())):
            callback(**kwargs)


class _License:
    def __init__(self, valid=True):
        self.valid = valid

    def has_valid_license(self):
        return self.valid


class _TransactionMonitor:
    def __init__(self):
        self.active = False

    def is_ost_active(self):
        return self.active


class _ProjectData:
    def __init__(self, bid_ref):
        self.bid_ref = bid_ref
        self.locked = False
        self.annotation_layer_visible = True

    def get_current_bid_ref(self):
        return self.bid_ref

    def is_current_bid_locked(self):
        return self.locked

    def is_annotation_layer_visible(self):
        return self.annotation_layer_visible


class _UiState:
    def __init__(self, bid_ref, page_uid="page-a"):
        self.bid_ref = bid_ref
        self.selected_file_path = bid_ref.file_path if bid_ref else None
        self.active_page_uid = page_uid
        self.place_condition_uid = None
        self.selected_project_uid = None
        self.highlighted_condition_uids = set()

    def get_selected_bid_ref(self):
        return self.bid_ref

    def is_database_selected(self):
        return bool(self.selected_file_path)


class _Capabilities:
    def __init__(self):
        self.database_editable = True
        self.locked_pages = set()
        self.requests = []

    def is_editable(self, database_id, resource=None):
        self.requests.append((database_id, resource))
        if not self.database_editable:
            return False
        return not (
            resource is not None
            and resource.resource_type == "page"
            and resource.resource_id in self.locked_pages
        )


class PlanSurfaceAccessTests(unittest.TestCase):
    def setUp(self):
        self.bid_ref = BidRef("project.mdb", "7")
        self.events = _EventBus()
        self.license = _License()
        self.transaction = _TransactionMonitor()
        self.project = _ProjectData(self.bid_ref)
        self.ui_state = _UiState(self.bid_ref)
        self.capabilities = _Capabilities()
        self.manager = UIAccessManager(
            self.events,
            self.license,
            self.transaction,
            self.project,
            self.ui_state,
            self.capabilities,
        )

    def tearDown(self):
        self.manager.cleanup()

    def _context(
        self,
        page_uid,
        *,
        surface_id="main-plan",
        bid_ref=None,
        database_id="project.mdb",
        layer_visible=True,
    ):
        return PlanSurfaceAccessContext(
            surface_id=surface_id,
            database_id=database_id,
            bid_ref=self.bid_ref if bid_ref is None else bid_ref,
            page_uid=page_uid,
            annotation_layer_visible=layer_visible,
        )

    def test_page_locks_are_evaluated_against_each_displayed_page(self):
        self.capabilities.locked_pages = {"page-b"}
        main = self.manager.get_plan_surface_access(self._context("page-a"))
        detached = self.manager.get_plan_surface_access(
            self._context("page-b", surface_id="detached-plan")
        )
        self.assertTrue(main.can_edit_page_settings)
        self.assertFalse(detached.can_edit_page_settings)
        self.assertTrue(main.can_place_annotations)
        self.assertTrue(detached.can_place_annotations)
        self.assertIn(
            (
                "project.mdb",
                ResourceRef("page", "page-b", 7),
            ),
            self.capabilities.requests,
        )

    def test_editable_detached_page_is_not_disabled_by_locked_main_page(self):
        self.capabilities.locked_pages = {"page-a"}
        main = self.manager.get_plan_surface_access(self._context("page-a"))
        detached = self.manager.get_plan_surface_access(
            self._context("page-b", surface_id="detached-plan")
        )
        self.assertFalse(main.can_edit_page_settings)
        self.assertTrue(detached.can_edit_page_settings)
        self.assertTrue(detached.can_place_annotations)

    def test_target_page_change_recalculates_page_resource(self):
        self.capabilities.locked_pages = {"page-b"}
        editable = self.manager.get_plan_surface_access(
            self._context("page-a", surface_id="detached-plan")
        )
        locked = self.manager.get_plan_surface_access(
            self._context("page-b", surface_id="detached-plan")
        )
        self.assertTrue(editable.can_edit_page_settings)
        self.assertFalse(locked.can_edit_page_settings)

    def test_missing_or_inconsistent_context_fails_closed(self):
        context = self._context("page-a", surface_id="detached-plan")
        invalid_contexts = (
            replace(context, surface_id=""),
            replace(context, database_id=""),
            replace(context, bid_ref=None),
            replace(context, page_uid=""),
            replace(context, database_id="other.mdb"),
            replace(context, bid_ref=BidRef("project.mdb", "8")),
        )
        requests_before = list(self.capabilities.requests)
        for invalid_context in invalid_contexts:
            with self.subTest(context=invalid_context):
                self.assertEqual(
                    self.manager.get_plan_surface_access(invalid_context),
                    PlanSurfaceAccessState(),
                )
        self.assertEqual(self.capabilities.requests, requests_before)

    def test_page_settings_lock_does_not_disable_annotation_capabilities(self):
        self.capabilities.locked_pages = {"page-a"}
        state = self.manager.get_plan_surface_access(self._context("page-a"))
        self.assertFalse(state.can_edit_page_settings)
        self.assertTrue(state.can_place_annotations)
        self.assertTrue(state.can_edit_annotations)
        self.assertTrue(state.can_edit_annotation_text)

    def test_hidden_annotation_layer_blocks_placement_not_other_mutations(self):
        state = self.manager.get_plan_surface_access(
            self._context("page-a", layer_visible=False)
        )
        self.assertFalse(state.can_place_annotations)
        self.assertTrue(state.can_edit_annotations)
        self.assertTrue(state.can_edit_annotation_text)
        self.assertTrue(state.can_edit_page_settings)

    def test_same_context_produces_same_main_and_detached_annotation_state(self):
        main = self.manager.get_plan_surface_access(
            self._context("page-a", surface_id="main-plan")
        )
        detached = self.manager.get_plan_surface_access(
            self._context("page-a", surface_id="detached-plan")
        )
        self.assertEqual(
            (
                main.can_place_annotations,
                main.can_edit_annotations,
                main.can_edit_annotation_text,
            ),
            (
                detached.can_place_annotations,
                detached.can_edit_annotations,
                detached.can_edit_annotation_text,
            ),
        )

    def test_surface_area_placement_preserves_only_its_own_continuation(self):
        self.manager.set_area_placement_active(True, surface_id="detached-plan")
        detached = self.manager.get_plan_surface_access(
            self._context("page-a", surface_id="detached-plan")
        )
        main = self.manager.get_plan_surface_access(
            self._context("page-a", surface_id="main-plan")
        )
        self.assertFalse(detached.can_place_annotations)
        self.assertTrue(detached.can_continue_annotation_placement)
        self.assertFalse(detached.can_edit_annotations)
        self.assertFalse(main.can_place_annotations)
        self.assertFalse(main.can_continue_annotation_placement)

    def test_one_surface_ending_does_not_clear_another_surface_blocker(self):
        self.manager.set_area_placement_active(True, surface_id=MAIN_PLAN_SURFACE_ID)
        self.manager.set_area_placement_active(True, surface_id="detached-plan")
        self.manager.clear_plan_surface_interaction("detached-plan")
        detached = self.manager.get_plan_surface_access(
            self._context("page-a", surface_id="detached-plan")
        )
        self.assertFalse(detached.can_continue_annotation_placement)

    def test_inline_text_edit_preserves_text_capability_only(self):
        self.manager.set_text_annotation_edit_active(True, surface_id="detached-plan")
        state = self.manager.get_plan_surface_access(
            self._context("page-a", surface_id="detached-plan")
        )
        self.assertFalse(state.can_place_annotations)
        self.assertFalse(state.can_edit_annotations)
        self.assertTrue(state.can_edit_annotation_text)
        self.assertFalse(state.can_edit_page_settings)

    def test_access_sources_notify_listeners_once_per_logical_change(self):
        calls = []
        self.manager.subscribe_access_state_changed(lambda: calls.append("refresh"))
        self.license.valid = False
        self.events.publish(AppEvents.LICENSE_EXPIRED)
        self.assertEqual(calls, [])
        self.events.publish(AppEvents.LICENSE_STATUS_CHANGED)
        self.assertEqual(calls, ["refresh"])
        self.transaction.active = True
        self.events.publish(AppEvents.OST_STATUS_CHANGED, active=True)
        self.assertEqual(calls, ["refresh", "refresh"])
        self.manager.refresh()
        self.assertEqual(calls, ["refresh", "refresh", "refresh"])
        self.manager.set_area_placement_active(True, surface_id=MAIN_PLAN_SURFACE_ID)
        self.assertEqual(len(calls), 4)
        self.manager.set_area_placement_active(True, surface_id=MAIN_PLAN_SURFACE_ID)
        self.assertEqual(len(calls), 4)
        self.manager.set_text_annotation_edit_active(True, surface_id="detached-plan")
        self.assertEqual(len(calls), 5)
        state = self.manager.get_plan_surface_access(self._context("page-a"))
        self.assertFalse(state.can_place_annotations)

    def test_inactive_surface_interactions_are_not_cached(self):
        self.manager.set_area_placement_active(True, surface_id="detached-plan")
        self.manager.set_area_placement_active(False, surface_id="detached-plan")
        self.assertNotIn("detached-plan", self.manager._surface_interactions)


if __name__ == "__main__":
    unittest.main()
