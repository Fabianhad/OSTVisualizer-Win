import math
import unittest
import tests.presentation.handlers.test_plan_view_action_handler as action_fixtures
from ost_visualizer.domain.entities.annotation import BidAnnotation
from ost_visualizer.presentation.services.undo_redo_service import UndoRedoService
from unittest.mock import patch


class TextAnnotationHistoryTests(unittest.TestCase):
    @staticmethod
    def committed():
        return action_fixtures.QueuedMutationResult(
            database_id="bid.mdb",
            runtime_generation=1,
            operation_id=str(action_fixtures.uuid.uuid4()),
            outcome_status=action_fixtures.MutationOutcomeStatus.COMMITTED,
        )

    def make_handler(self, sql=False):
        data = action_fixtures.FakeProjectData()
        ann = BidAnnotation(
            uid="a1",
            annotation_type="text",
            page_uid="p1",
            position=[10, 10, 80, 24],
            properties={"Text": "Before"},
        )
        data.annotations = [ann]
        plan = action_fixtures.FakePlanView(data)
        plan.annotations = {"a1": ann}
        plan.annotation_key_map = {("a1", "text"): "a1"}
        writer = action_fixtures.FakeAnnotationWriteService()
        write = action_fixtures.FakeWriteService()
        write.sql_collaboration_mutations = sql
        undo = UndoRedoService()
        undo.set_active_bid(action_fixtures.FakeUiState().get_selected_bid_ref())
        handler = action_fixtures.PlanViewActionHandlerTests()._paste_handler(
            data=data, plan_view=plan, ann_write=writer, undo=undo, write=write
        )
        return handler, data, writer, write, undo

    def complete_edit(self, kind, data, write):
        if kind in {"position", "rotation"}:
            _database, _bid, payload, callback = write.queued_geometry[-1]
            data.update_annotation_positions(payload["annotation_positions"])
        else:
            _database, _bid, _kind, updates, _options, callback = (
                write.queued_properties[-1]
            )
            if kind == "text":
                data.update_annotation_text_properties(updates)
            else:
                data.update_annotation_styles(updates)
        callback(self.committed())

    def test_older_edit_follows_delete_restore_instead_of_reused_uid(self):
        for sql in (False, True):
            for kind in ("text", "style", "position", "rotation"):
                with self.subTest(sql=sql, kind=kind):
                    handler, data, writer, write, undo = self.make_handler(sql)
                    original = data.annotations[0]
                    if kind == "text":
                        before, after = "Before", "After"
                        value = lambda item: item.properties["Text"]
                        handler.on_annotation_text_properties_flushed(
                            [("a1", "text", {"Text": before}, {"Text": after})]
                        )
                    elif kind == "style":
                        before, after = original.color, "#0000ff"
                        value = lambda item: item.color
                        handler.on_annotation_styles_flushed(
                            [("a1", "text", {"Color": before}, {"Color": after})]
                        )
                    else:
                        before, after = list(original.position), [10.015625, 10, 80, 24]
                        value = lambda item: item.position
                        if kind == "rotation":
                            after = [10, 10, 80, 24, math.pi / 3]
                            handler.on_group_rotation_flushed(
                                [], [("a1", "text", before, after)], []
                            )
                        else:
                            handler.on_positions_flushed(
                                [], [("a1", "text", before, after)]
                            )
                    if sql:
                        self.complete_edit(kind, data, write)
                    handler.on_elements_deleted(["a1"])
                    if sql:
                        data.remove_annotations_by_keys([("a1", "text")])
                        write.queued_deletes[-1][-1](self.committed())
                    self.assertEqual(data.annotations, [])
                    for cycle in range(2):
                        writer.next_uids = [f"restored-{cycle}"]
                        undo.undo()
                        if sql:
                            db, payload, _options, callback = write.queued_pastes[-1]
                            result = write.execute_plan_items_paste_local(db, payload)
                            handler._project_mdb_plan_items_paste(
                                action_fixtures.FakeUiState().get_selected_bid_ref(),
                                payload,
                                result,
                            )
                            callback(result)
                        restored = next(
                            item
                            for item in data.annotations
                            if item.uid == f"restored-{cycle}"
                        )
                        reused = BidAnnotation(
                            uid="a1",
                            annotation_type="text",
                            page_uid="p1",
                            position=[999, 999, 1, 1],
                            properties={"Text": "Unrelated"},
                        )
                        data.annotations.append(reused)
                        undo.undo()
                        if sql:
                            self.complete_edit(kind, data, write)
                        self.assertEqual(value(restored), before)
                        self.assertEqual(reused.properties["Text"], "Unrelated")
                        self.assertEqual(reused.position, [999, 999, 1, 1])
                        self.assertEqual(reused.color, "#FF0000")
                        undo.redo()
                        if sql:
                            self.complete_edit(kind, data, write)
                        self.assertEqual(value(restored), after)
                        undo.redo()
                        if sql:
                            data.remove_annotations_by_keys([(restored.uid, "text")])
                            write.queued_deletes[-1][-1](self.committed())
                        self.assertEqual(data.annotations, [reused])
                        data.annotations.clear()

    def test_late_sql_edit_completion_does_not_recreate_cleared_history(self):
        handler, data, _writer, write, undo = self.make_handler(True)
        handler.on_annotation_text_properties_flushed(
            [("a1", "text", {"Text": "Before"}, {"Text": "After"})]
        )
        undo.clear()
        self.complete_edit("text", data, write)
        self.assertFalse(undo.can_undo())

    def test_creation_undo_after_independent_delete_restore_uses_restored_identity(
        self,
    ):
        handler, data, writer, _write, undo = self.make_handler()
        data.annotations.clear()
        writer.next_uids = ["a1"]
        handler.on_text_annotation_created([10, 10, 80, 24], "p1", {"Text": "Created"})
        created = data.annotations[0]
        handler._plan_view.annotations = {"a1": created}
        handler.on_elements_deleted(["a1"])
        writer.next_uids = ["restored"]
        undo.undo()
        reused = BidAnnotation(
            uid="a1",
            annotation_type="text",
            page_uid="p1",
            properties={"Text": "Unrelated"},
        )
        data.annotations.append(reused)
        undo.undo()
        self.assertEqual(data.annotations, [reused])

    def test_create_edit_move_resize_undo_redo_chain_preserves_exact_geometry(self):
        handler, data, writer, _write, undo = self.make_handler()
        data.annotations.clear()
        initial = [10.015625, 10, 80.000125, 24]
        writer.next_uids = ["a1"]
        handler.on_text_annotation_created(initial, "p1", {"Text": "Before"})
        handler.on_annotation_text_properties_flushed(
            [("a1", "text", {"Text": "Before"}, {"Text": "After"})]
        )
        moved = [11.015625, 10, 80.000125, 24]
        resized = [11.015625, 10, 85.000125, 30.25]
        handler.on_positions_flushed([], [("a1", "text", initial, moved)])
        handler.on_positions_flushed([], [("a1", "text", moved, resized)])
        for _ in range(4):
            undo.undo()
        self.assertEqual(data.annotations, [])
        writer.next_uids = ["reallocated"]
        for _ in range(4):
            undo.redo()
        self.assertEqual(len(data.annotations), 1)
        self.assertEqual(data.annotations[0].uid, "reallocated")
        self.assertEqual(data.annotations[0].position, resized)
        self.assertEqual(data.annotations[0].properties["Text"], "After")

    def test_sql_geometry_history_replays_at_current_page_scale(self):
        handler, data, _writer, write, undo = self.make_handler(True)
        handler.on_positions_flushed(
            [], [("a1", "text", [10, 10, 80, 24], [20, 10, 80, 24])]
        )
        self.complete_edit("position", data, write)
        data.pages["p1"].scale_factor2 = 2.0
        undo.undo()
        self.assertEqual(
            write.queued_geometry[-1][2]["annotation_positions"],
            [("a1", "text", [20, 20, 160, 48])],
        )


class DetachedTextHistoryTests(unittest.TestCase):
    def setUp(self):
        import tests.integration.surfaces.test_presentation as surfaces

        surfaces.CrossSurfacePresentationTests.setUpClass()
        self.fixture = surfaces.CrossSurfacePresentationTests()

        class TextPageData(surfaces.SharedPageData):
            add_annotations = action_fixtures.FakeProjectData.add_annotations
            remove_annotations_by_keys = (
                action_fixtures.FakeProjectData.remove_annotations_by_keys
            )
            update_annotation_text_properties = (
                action_fixtures.FakeProjectData.update_annotation_text_properties
            )
            update_annotation_positions = (
                action_fixtures.FakeProjectData.update_annotation_positions
            )
            update_annotation_styles = (
                action_fixtures.FakeProjectData.update_annotation_styles
            )
            get_current_bid_file_path = (
                action_fixtures.FakeProjectData.get_current_bid_file_path
            )

            def __init__(self):
                super().__init__()
                self.added_annotations = []
                self.removed_annotation_uids = []

        with patch.object(surfaces, "SharedPageData", TextPageData):
            self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        f = self.fixture
        self.write = action_fixtures.FakeWriteService()
        self.handler = action_fixtures.PlanViewActionHandlerTests._paste_handler(
            f, plan_view=f.main_plan, write=self.write, data=f.data
        )
        self.handler._ui_state = f.state
        self.window = f.detached
        self.window._annotation_write_coordinator = self.handler._annotation_writes
        self.window._project_write_svc = self.write
        self.window._file_path = f.bid_ref.file_path
        self.history = UndoRedoService(event_bus=f.bus)
        self.history.set_active_bid(f.bid_ref)
        self.window._undo_svc = self.history
        self.window.plan_view.undo_requested.connect(self.history.undo)
        self.window.plan_view.redo_requested.connect(self.history.redo)
        f.data.annotations = [
            BidAnnotation(
                uid="text",
                annotation_type="text",
                page_uid=f.data.page.uid,
                position=[10, 10, 80, 24],
                properties={"Text": "After"},
            )
        ]
        f.refresh()

    def test_late_sql_text_completion_cannot_recreate_invalidated_history(self):
        self.window._queue_sql_annotation_properties(
            self.fixture.bid_ref.file_path,
            "annotation_text",
            [("text", "text", {"Text": "Before"}, {"Text": "After"})],
            lambda: None,
        )
        self.history.clear()
        self.write.queued_properties[-1][-1](TextAnnotationHistoryTests.committed())
        self.assertFalse(self.history.can_undo())

    def test_detached_sql_history_rebinds_deleted_text_and_rescales_geometry(self):
        f = self.fixture
        self.window._push_sql_annotation_geometry_history(
            f.bid_ref,
            [("text", "text", [10, 10, 80, 24])],
            [("text", "text", [20, 10, 80, 24])],
            (f.data.page.uid,),
        )
        from ost_visualizer.presentation.services.undo_redo_service import (
            AnnotationHistoryTarget,
        )

        suspended = self.history.suspend_deleted_annotations(
            f.bid_ref,
            (AnnotationHistoryTarget(f.bid_ref, f.data.page.uid, "text", "text"),),
        )
        original = f.data.annotations[0]
        original.uid = "restored"
        f.data.annotations.append(
            BidAnnotation(
                uid="text",
                annotation_type="text",
                page_uid=f.data.page.uid,
                position=[999, 999, 1, 1],
                properties={"Text": "Unrelated"},
            )
        )
        self.history.rebind_restored_annotations(
            f.bid_ref, {(f.data.page.uid, "text", "text"): "restored"}, suspended
        )
        f.data.page.scale_factor2 *= 2
        self.history.undo()
        payload = self.write.queued_geometry[-1][2]
        self.assertEqual(
            payload["annotation_positions"], [("restored", "text", [20, 20, 160, 48])]
        )

    def test_detached_local_edit_delete_restore_rebinds_older_history(self):
        f = self.fixture
        writer = action_fixtures.FakeAnnotationWriteService()
        self.window._ann_write_svc = writer
        self.write.annotation_write_service = writer
        from ost_visualizer.presentation.services.annotation_write_coordinator import (
            AnnotationWriteCoordinator,
        )

        self.window._annotation_write_coordinator = AnnotationWriteCoordinator(
            writer, f.data, f.bus
        )
        self.window._text_editing_enabled = lambda: True
        self.window._editing_enabled = lambda: True
        self.window._on_annotation_text_properties_flushed(
            [("text", "text", {"Text": "Before"}, {"Text": "After"})]
        )
        self.window._on_elements_deleted(["text"])
        self.assertEqual(f.data.annotations, [])
        writer.next_uids = ["restored"]
        self.history.undo()
        self.assertEqual(f.data.annotations[0].uid, "restored")
        f.data.annotations.append(
            BidAnnotation(
                uid="text",
                annotation_type="text",
                page_uid=f.data.page.uid,
                properties={"Text": "Unrelated"},
            )
        )
        self.history.undo()
        self.assertEqual(f.data.annotations[0].properties["Text"], "Before")
        self.assertEqual(f.data.annotations[1].properties["Text"], "Unrelated")
        self.history.redo()
        self.assertEqual(f.data.annotations[0].properties["Text"], "After")
        self.history.redo()
        self.assertEqual([a.uid for a in f.data.annotations], ["text"])

    def test_main_history_rejects_text_deleted_in_detached_then_uid_reused(self):
        f = self.fixture
        main_history = UndoRedoService(event_bus=f.bus)
        main_history.set_active_bid(f.bid_ref)
        self.handler._undo_svc = main_history
        f.coordinator._undo_service = main_history
        from ost_visualizer.application.events.app_events import AppEvents

        f.bus.subscribe(
            AppEvents.ANNOTATION_LIFETIMES_DELETED,
            f.coordinator._on_annotation_lifetimes_deleted,
        )
        self.window._ann_write_svc = action_fixtures.FakeAnnotationWriteService()
        self.window._editing_enabled = lambda: True
        self.handler.on_annotation_text_properties_flushed(
            [("text", "text", {"Text": "Before"}, {"Text": "After"})]
        )
        self.window._on_elements_deleted(["text"])
        f.data.annotations.append(
            BidAnnotation(
                uid="text",
                annotation_type="text",
                page_uid=f.data.page.uid,
                properties={"Text": "Unrelated"},
            )
        )
        main_history.undo()
        self.assertEqual(f.data.annotations[0].properties["Text"], "Unrelated")

    def test_late_detached_sql_delete_still_invalidates_other_window_history(self):
        f = self.fixture
        main_history = UndoRedoService(event_bus=f.bus)
        main_history.set_active_bid(f.bid_ref)
        self.handler._undo_svc = main_history
        f.coordinator._undo_service = main_history
        from ost_visualizer.application.events.app_events import AppEvents

        f.bus.subscribe(
            AppEvents.ANNOTATION_LIFETIMES_DELETED,
            f.coordinator._on_annotation_lifetimes_deleted,
        )
        self.handler.on_annotation_text_properties_flushed(
            [("text", "text", {"Text": "Before"}, {"Text": "After"})]
        )
        self.window._queue_sql_annotation_delete(
            f.bid_ref, list(f.data.annotations), set(), {("text", "text")}
        )
        self.history.clear()
        f.data.annotations.clear()
        self.write.queued_deletes[-1][-1](TextAnnotationHistoryTests.committed())
        f.data.annotations.append(
            BidAnnotation(
                uid="text",
                annotation_type="text",
                page_uid=f.data.page.uid,
                properties={"Text": "Unrelated"},
            )
        )
        main_history.undo()
        self.assertEqual(f.data.annotations[0].properties["Text"], "Unrelated")
        self.assertFalse(self.history.can_undo())


class AnnotationDeletionScopeTests(unittest.TestCase):
    def test_shared_delete_command_keeps_source_reference_map_across_repeated_restores(
        self,
    ):
        from ost_visualizer.presentation.services.selection_commands import (
            DeleteAnnotationsCommand,
        )

        handler, data, writer, _write, undo = (
            TextAnnotationHistoryTests().make_handler()
        )
        bid = action_fixtures.FakeUiState().get_selected_bid_ref()
        saved = [
            BidAnnotation(
                uid="view",
                annotation_type="namedview",
                page_uid="p1",
                position=[0, 0, 10, 10],
                properties={"Text": "View"},
            ),
            BidAnnotation(
                uid="link",
                annotation_type="hotlink",
                page_uid="p1",
                position=[0, 0, 10, 10],
                properties={"BidPageViewUID": "view"},
            ),
        ]
        data.annotations.clear()
        coordinator = handler._annotation_writes
        binding = coordinator.history_from_saved(bid, saved, undo)
        binding.suspend()
        command = DeleteAnnotationsCommand(
            saved,
            bid,
            handler._plan_view,
            lambda bid, saved: coordinator.insert_saved_annotations(
                bid, saved, execute_paste=_write.execute_plan_items_paste_local
            ),
            coordinator.delete_saved_annotations,
            history=binding,
        )
        undo.push_local(
            command.undo,
            command.redo,
            annotation_targets=tuple(binding.targets.values()),
        )
        for cycle in range(2):
            writer.next_uids = [f"view-{cycle}", f"link-{cycle}"]
            undo.undo()
            self.assertEqual(len(data.annotations), 2)
            link = next(
                item for item in data.annotations if item.annotation_type == "hotlink"
            )
            self.assertEqual(str(link.properties["BidPageViewUID"]), f"view-{cycle}")
            undo.redo()
            self.assertEqual(data.annotations, [])
