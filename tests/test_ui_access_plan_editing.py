import unittest
from contextlib import nullcontext
from types import SimpleNamespace
from ost_visualizer.application.dtos.collaboration_dtos import (
    DatabaseMutationResult,
    MutationOutcomeStatus,
    ResourceRef,
)
from ost_visualizer.application.services.annotation_write_service import (
    AnnotationWriteService,
)
from ost_visualizer.application.services.base_write_service import (
    DatabaseMutationWriteService,
)
from ost_visualizer.domain.entities.identity_refs import BidRef
from ost_visualizer.presentation.components.plan_view.components.input_handler import (
    InputHandlerMixin,
)
from ost_visualizer.presentation.components.plan_view.view import TakeoffPlanView
from ost_visualizer.presentation.modes.cursor import CURSOR_MODE_PLACE


class _EventBus:
    def publish(self, *_args, **_kwargs):
        pass


class _CapabilityService:
    def __init__(self, editable: bool, denied_resource=None) -> None:
        self.editable = editable
        self.denied_resource = denied_resource
        self.requests = []

    def is_editable(self, database_id, resource=None) -> bool:
        self.requests.append((database_id, resource))
        return self.editable and (resource is None or resource != self.denied_resource)


class _MutationExecutor:
    def __init__(self) -> None:
        self.calls = 0

    def execute(self, request, operation):
        self.calls += 1
        return DatabaseMutationResult(
            operation_id=request.operation_id,
            outcome_status=MutationOutcomeStatus.COMMITTED,
            value=operation(SimpleNamespace()),
        )


class _SessionRegistry:
    def get(self, _database_id):
        return "session"

    def lock_tokens(self, _database_id, _resources):
        return ()


class _ConcurrencyTokens:
    def __init__(self) -> None:
        self.load_calls = 0

    def ensure_resources_loaded(self, _database_id, _resources):
        self.load_calls += 1

    def mutation_scope(self, _database_id):
        return nullcontext()

    def expected_versions(self, _database_id, _resources):
        return ()

    def apply_result(self, _database_id, _versions):
        pass


class UIAccessPlanEditingTests(unittest.TestCase):
    def test_annotation_resources_keep_bid_identity_for_equivalent_windows_path(self):
        service = AnnotationWriteService.__new__(AnnotationWriteService)
        service._project_data = SimpleNamespace(
            get_current_bid_ref=lambda: BidRef(
                file_path=r"C:\Jobs\Current.mdb",
                bid_uid="41",
            )
        )
        self.assertEqual(service._bid_uid("c:/jobs/CURRENT.mdb"), 41)

    def test_revoking_plan_editing_cancels_every_active_mutation_mode(self):
        cancellations = []

        def cancel_rotation_drag():
            cancellations.append(("rotation-drag", True))
            return False

        view = SimpleNamespace(
            _editing_enabled=True,
            _rotation_drag_active=False,
            _position_before_edit={},
            _rotation_before_edit={},
            _current_takeoffs={},
            _current_annotations={},
            _dirty_positions={},
            _dirty_ann_positions={},
            _dirty_rotations={},
            _keyboard_move_dirty=False,
            _cancel_active_drag_interaction=lambda restore_preview: cancellations.append(
                ("drag", restore_preview)
            ),
            _cancel_rotation_drag_interaction=cancel_rotation_drag,
            cancel_overlay_move_mode=lambda restore_preview: cancellations.append(
                ("overlay", restore_preview)
            ),
            finish_intelligent_paste_placement=lambda: cancellations.append(
                ("intelligent-paste", True)
            ),
            cancel_paste_backout=lambda: cancellations.append(("paste-backout", True)),
            cancel_place_mode=lambda: cancellations.append(("placement", True)),
            _finish_active_inline_text_edit=lambda commit: cancellations.append(
                ("inline-text", commit)
            ),
            _remove_rotate_handle=lambda: cancellations.append(("rotate", True)),
            _rebuild_current_overlays_from_model=lambda: None,
        )
        TakeoffPlanView.set_editing_enabled(view, False)
        self.assertIn(("drag", True), cancellations)
        self.assertIn(("rotation-drag", True), cancellations)
        self.assertIn(("overlay", True), cancellations)
        self.assertIn(("intelligent-paste", True), cancellations)
        self.assertIn(("paste-backout", True), cancellations)
        self.assertIn(("placement", True), cancellations)
        self.assertIn(("inline-text", False), cancellations)

    def test_read_only_plan_rejects_direct_mutation_mode_activation(self):
        calls = []
        view = SimpleNamespace(
            _editing_enabled=False,
            _finish_inline_text_edit_before_tool_change=lambda: calls.append(
                "finish-text"
            )
            or True,
            cancel_overlay_move_mode=lambda restore_preview: calls.append(
                ("overlay", restore_preview)
            ),
            _remove_rotate_handle=lambda: calls.append("remove-rotate"),
            finish_intelligent_paste_placement=lambda: calls.append("finish-paste"),
            _exit_annotation_place_mode=lambda: calls.append("exit-annotation"),
            enter_place_mode=lambda: calls.append("enter-place") or True,
            _exit_place_mode=lambda: calls.append("exit-place"),
            _clear_backout_state=lambda: calls.append("clear-backout"),
            _apply_cursor_mode=lambda mode: calls.append(("cursor", mode)),
            cursor_mode_change_requested=SimpleNamespace(
                emit=lambda mode: calls.append(("emit", mode))
            ),
        )
        TakeoffPlanView.set_cursor_mode(view, CURSOR_MODE_PLACE)
        self.assertEqual(calls, [])

    def test_read_only_plan_rejects_direct_annotation_style_mutation(self):
        annotation = SimpleNamespace(
            color="#112233",
            width=2.0,
            is_text=False,
            is_dimension=False,
            is_highlight=False,
            annotation_type="rectangle",
            properties={},
        )
        emissions = []
        view = SimpleNamespace(
            _editing_enabled=False,
            _selected_uids={"annotation-1"},
            _current_annotations={"annotation-1": annotation},
            _ann_db_uid_map={"annotation-1": 41},
            _rebuild_current_overlays_from_model=lambda: emissions.append("rebuild"),
            annotation_styles_flushed=SimpleNamespace(
                emit=lambda changes: emissions.append(changes)
            ),
        )
        TakeoffPlanView.apply_annotation_style_to_selection(
            view, color="#445566", width=4.0
        )
        self.assertEqual(annotation.color, "#112233")
        self.assertEqual(annotation.width, 2.0)
        self.assertEqual(emissions, [])

    def test_stale_mouse_release_cannot_commit_after_access_revocation(self):
        event = SimpleNamespace(accepted=False)
        event.accept = lambda: setattr(event, "accepted", True)
        view = SimpleNamespace(
            _editing_enabled=False,
            _cursor_mode=CURSOR_MODE_PLACE,
            _editing_cursor_mode_allowed=lambda: False,
        )
        InputHandlerMixin.mouseReleaseEvent(view, event)
        self.assertTrue(event.accepted)

    def test_application_mutation_boundary_rejects_revoked_database_access(self):
        capability = _CapabilityService(editable=False)
        executor = _MutationExecutor()
        tokens = _ConcurrencyTokens()
        service = DatabaseMutationWriteService(
            reload_database=lambda _database_id: True,
            event_bus=_EventBus(),
            mutation_executor=executor,
            session_registry=_SessionRegistry(),
            concurrency_tokens=tokens,
            database_capability_service=capability,
        )
        resource = ResourceRef("takeoff", "41", 7)
        result = service._execute_database_mutation(
            "sql-db", (resource,), lambda _recorder: True
        )
        self.assertEqual(result.outcome_status, MutationOutcomeStatus.REJECTED)
        self.assertEqual(executor.calls, 0)
        self.assertEqual(tokens.load_calls, 0)
        self.assertEqual(
            capability.requests,
            [("sql-db", None)],
        )

    def test_application_mutation_boundary_preserves_editable_access_path(self):
        capability = _CapabilityService(editable=True)
        executor = _MutationExecutor()
        tokens = _ConcurrencyTokens()
        service = DatabaseMutationWriteService(
            reload_database=lambda _database_id: True,
            event_bus=_EventBus(),
            mutation_executor=executor,
            session_registry=_SessionRegistry(),
            concurrency_tokens=tokens,
            database_capability_service=capability,
        )
        resource = ResourceRef("takeoff", "41", 7)
        result = service._execute_database_mutation(
            "access-db", (resource,), lambda _recorder: True
        )
        self.assertEqual(result.outcome_status, MutationOutcomeStatus.COMMITTED)
        self.assertEqual(executor.calls, 1)
        self.assertEqual(tokens.load_calls, 1)

    def test_application_mutation_boundary_rejects_locked_resource(self):
        resource = ResourceRef("takeoff", "41", 7)
        capability = _CapabilityService(editable=True, denied_resource=resource)
        executor = _MutationExecutor()
        tokens = _ConcurrencyTokens()
        service = DatabaseMutationWriteService(
            reload_database=lambda _database_id: True,
            event_bus=_EventBus(),
            mutation_executor=executor,
            session_registry=_SessionRegistry(),
            concurrency_tokens=tokens,
            database_capability_service=capability,
        )
        result = service._execute_database_mutation(
            "sql-db", (resource,), lambda _recorder: True
        )
        self.assertEqual(result.outcome_status, MutationOutcomeStatus.REJECTED)
        self.assertEqual(executor.calls, 0)
        self.assertEqual(tokens.load_calls, 0)
        self.assertEqual(
            capability.requests,
            [("sql-db", None), ("sql-db", resource)],
        )


if __name__ == "__main__":
    unittest.main()
