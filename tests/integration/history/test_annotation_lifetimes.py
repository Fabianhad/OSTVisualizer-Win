import math
import unittest
import tests.presentation.handlers.test_plan_view_action_handler as action_fixtures
from ost_visualizer.domain.entities.annotation import BidAnnotation
from ost_visualizer.presentation.handlers import (
    plan_view_action_handler as handler_module,
)
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

    def test_delete_undo_restores_annotation_at_current_page_scale(self):
        for sql in (False, True):
            with self.subTest(sql=sql):
                handler, data, writer, write, undo = self.make_handler(sql)
                handler.on_elements_deleted(["a1"])
                if sql:
                    data.remove_annotations_by_keys([("a1", "text")])
                    write.queued_deletes[-1][-1](self.committed())
                self.assertEqual(data.annotations, [])
                # The page is recalibrated 1:1 -> 1:2 after the delete; the
                # restore must follow the page, not the geometry at delete time.
                data.pages["p1"].scale_factor2 = 2.0
                undo.undo()
                specs = (
                    write.queued_pastes[-1][1].annotation_specs
                    if sql
                    else writer.insert_calls[-1][2]
                )
                self.assertEqual([spec.position for spec in specs], [[20, 20, 160, 48]])
                self.assertEqual(specs[0].properties["Text"], "Before")

    def test_late_sql_edit_completion_does_not_recreate_cleared_history(self):
        # Positive control: an undisturbed completion does record history.
        control, control_data, _writer, control_write, control_undo = self.make_handler(
            True
        )
        control.on_annotation_text_properties_flushed(
            [("a1", "text", {"Text": "Before"}, {"Text": "After"})]
        )
        self.assertFalse(control_undo.can_undo())
        self.complete_edit("text", control_data, control_write)
        self.assertTrue(control_undo.can_undo())
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
        queue = lambda: self.window._queue_sql_annotation_properties(
            self.fixture.bid_ref.file_path,
            "annotation_text",
            [("text", "text", {"Text": "Before"}, {"Text": "After"})],
            lambda: None,
        )
        # Positive control: an undisturbed completion does record history.
        queue()
        self.write.queued_properties[-1][-1](TextAnnotationHistoryTests.committed())
        self.assertTrue(self.history.can_undo())
        self.history.clear()
        queue()
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
        # The restore inserts the Named View first and its dependents second, so
        # the fake allocator must hand out one UID per inserted annotation.
        allocated = []
        record_insert = writer.insert_annotations

        def allocate(*args, **kwargs):
            specs = args[2]
            record_insert(*args, **kwargs)
            return [allocated.pop(0) for _ in specs]

        writer.insert_annotations = allocate
        for cycle in range(2):
            allocated[:] = [f"view-{cycle}", f"link-{cycle}"]
            undo.undo()
            self.assertEqual(len(data.annotations), 2)
            link = next(
                item for item in data.annotations if item.annotation_type == "hotlink"
            )
            self.assertEqual(str(link.properties["BidPageViewUID"]), f"view-{cycle}")
            # The history targets follow each family's own restored identity.
            self.assertEqual(
                {t.annotation_type: t.uid for t in binding.targets.values()},
                {"namedview": f"view-{cycle}", "hotlink": f"link-{cycle}"},
            )
            self.assertTrue(all(t.available for t in binding.targets.values()))
            undo.redo()
            self.assertFalse(any(t.available for t in binding.targets.values()))
            self.assertEqual(data.annotations, [])


class HotlinkViewLifetimeHistoryTests(unittest.TestCase):
    """A deleted Hot Link follows its Named View when an accepted restore map
    reactivates it, on every history path that retains the Hot Link's spec."""

    def setUp(self):
        # A refused restore reports through this dialog; it must not block the run.
        patcher = patch.object(handler_module, "show_warning")
        self.warning = patcher.start()
        self.addCleanup(patcher.stop)

    def make(self, sql=False):
        handler, data, writer, write, undo = TextAnnotationHistoryTests().make_handler(
            sql
        )
        self.view = BidAnnotation(
            uid="view",
            annotation_type="namedview",
            page_uid="p1",
            position=[0, 0, 10, 10],
            properties={"Text": "View"},
        )
        self.link = BidAnnotation(
            uid="link",
            annotation_type="hotlink",
            page_uid="p1",
            position=[20, 20],
            properties={"BidPageViewUID": "view"},
        )
        data.annotations = [self.view, self.link]
        self.bid = action_fixtures.FakeUiState().get_selected_bid_ref()
        return handler, data, writer, write, undo

    @staticmethod
    def delete_history(handler, data, item):
        data.annotations.remove(item)
        handler._push_mdb_delete_history(
            handler._ui_state.get_selected_bid_ref(),
            [],
            [item],
            {},
            [],
            [(item.uid, item.annotation_type)],
            (),
        )

    @staticmethod
    def restored_target(writer):
        specs = writer.insert_calls[-1][2]
        return specs[0].properties["BidPageViewUID"]

    def test_mdb_delete_history_hotlink_follows_restored_named_view(self):
        handler, data, writer, _write, undo = self.make()
        self.delete_history(handler, data, self.link)
        self.delete_history(handler, data, self.view)
        for cycle in range(2):
            view_uid = f"view-{cycle}"
            writer.next_uids = [view_uid]
            undo.undo()
            self.assertEqual([a.uid for a in data.annotations], [view_uid])
            writer.next_uids = [f"link-{cycle}"]
            undo.undo()
            self.assertEqual(self.restored_target(writer), view_uid)
            links = [a for a in data.annotations if a.annotation_type == "hotlink"]
            self.assertEqual(
                [(a.uid, a.properties["BidPageViewUID"]) for a in links],
                [(f"link-{cycle}", view_uid)],
            )
            undo.redo()
            undo.redo()
            self.assertEqual(data.annotations, [])
        self.warning.assert_not_called()

    def test_mdb_delete_history_refuses_hotlink_when_named_view_was_not_restored(
        self,
    ):
        handler, data, writer, _write, undo = self.make()
        self.delete_history(handler, data, self.link)
        # The Named View is deleted by another history owner and never restored
        # here, then an unrelated Named View takes over its UID.
        data.annotations.clear()
        undo.invalidate_deleted_annotation_lifetimes(
            self.bid.file_path, self.bid.bid_uid, {("p1", "namedview", "view")}, "other"
        )
        data.annotations.append(
            BidAnnotation(
                uid="view",
                annotation_type="namedview",
                page_uid="p1",
                position=[0, 0, 10, 10],
                properties={"Text": "Unrelated"},
            )
        )
        undo.undo()
        self.warning.assert_called_once()
        self.assertIn("Named View", self.warning.call_args.args[2])
        self.assertEqual(writer.insert_calls, [])
        self.assertEqual([a.uid for a in data.annotations], ["view"])
        self.assertTrue(undo.can_undo())

    @staticmethod
    def sql_result(payload=None, new_uids=()):
        maps = ()
        if payload is not None:
            maps = (
                (
                    "annotations",
                    tuple(zip(payload.annotation_source_uids, new_uids)),
                ),
            )
        return action_fixtures.QueuedMutationResult(
            database_id="bid.mdb",
            runtime_generation=1,
            operation_id=str(action_fixtures.uuid.uuid4()),
            outcome_status=action_fixtures.MutationOutcomeStatus.COMMITTED,
            authoritative_result=action_fixtures.AuthoritativeMutationResult(
                created_uid_maps=maps
            ),
        )

    def restore_view_through_sql_undo(self, data, write, undo, new_uid):
        undo.undo()
        _db, payload, _options, callback = write.queued_pastes[-1]
        self.assertEqual(
            [spec.annotation_type for spec in payload.annotation_specs], ["namedview"]
        )
        data.annotations.append(
            BidAnnotation(
                uid=new_uid,
                annotation_type="namedview",
                page_uid="p1",
                position=[0, 0, 10, 10],
                properties={"Text": "View"},
            )
        )
        callback(self.sql_result(payload, [new_uid]))

    def test_sql_delete_history_hotlink_follows_restored_named_view(self):
        handler, data, _writer, write, undo = self.make(sql=True)
        for item in (self.link, self.view):
            data.annotations.remove(item)
            handler._push_sql_delete_history(
                self.bid, [], [item], {}, [], [(item.uid, item.annotation_type)]
            )
        self.restore_view_through_sql_undo(data, write, undo, "view-2")
        undo.undo()
        payload = write.queued_pastes[-1][1]
        self.assertEqual(
            [spec.annotation_type for spec in payload.annotation_specs], ["hotlink"]
        )
        self.assertEqual(
            payload.annotation_specs[0].properties["BidPageViewUID"], "view-2"
        )
        self.warning.assert_not_called()

    def test_sql_paste_history_redo_hotlink_follows_restored_named_view(self):
        from ost_visualizer.application.dtos.collaboration_dtos import (
            PlanItemsPastePayload,
        )
        from ost_visualizer.application.dtos.collaboration_resource_catalog import (
            annotation_resource_id,
        )
        from ost_visualizer.application.dtos.insert_annotation_spec_dto import (
            InsertAnnotationSpec,
        )

        handler, data, _writer, write, undo = self.make(sql=True)
        source = annotation_resource_id("hotlink", "placed")
        payload = PlanItemsPastePayload(
            source_bid_uid="7",
            destination_bid_uid="7",
            annotation_source_uids=(source,),
            annotation_specs=(
                InsertAnnotationSpec(
                    page_uid="p1",
                    annotation_type="hotlink",
                    position=[30.0, 30.0],
                    color="#ff0000",
                    width=1.0,
                    properties={"BidPageViewUID": "view"},
                ),
            ),
        )
        handler._push_sql_paste_history(self.bid, payload, {}, {source: "link"})
        data.annotations.remove(self.view)
        handler._push_sql_delete_history(
            self.bid, [], [self.view], {}, [], [("view", "namedview")]
        )
        self.restore_view_through_sql_undo(data, write, undo, "view-2")
        # Undo the placement (a delete), then redo it onto the restored view.
        undo.undo()
        write.queued_deletes[-1][-1](self.sql_result())
        pastes_before = len(write.queued_pastes)
        undo.redo()
        self.assertEqual(len(write.queued_pastes), pastes_before + 1)
        spec = write.queued_pastes[-1][1].annotation_specs[0]
        self.assertEqual(spec.properties["BidPageViewUID"], "view-2")
        # The retained placement spec itself is untouched, so later restores
        # resolve from the original target again.
        self.assertEqual(
            payload.annotation_specs[0].properties["BidPageViewUID"], "view"
        )
        self.warning.assert_not_called()


class DetachedHotlinkViewHistoryTests(unittest.TestCase):
    """The detached Plan window's annotation history follows a restored Named
    View exactly like the main Plan handler does."""

    def setUp(self):
        DetachedTextHistoryTests.setUp(self)
        from ost_visualizer.presentation.windows.components import (
            window as window_module,
        )

        # A refused restore reports through this dialog; it must not block the run.
        patcher = patch.object(window_module, "show_warning")
        self.warning = patcher.start()
        self.addCleanup(patcher.stop)
        f = self.fixture
        self.writer = action_fixtures.FakeAnnotationWriteService()
        self.window._ann_write_svc = self.writer
        self.write.annotation_write_service = self.writer
        from ost_visualizer.presentation.services.annotation_write_coordinator import (
            AnnotationWriteCoordinator,
        )

        self.window._annotation_write_coordinator = AnnotationWriteCoordinator(
            self.writer, f.data, f.bus
        )
        self.window._editing_enabled = lambda: True
        self.page = f.data.page.uid
        self.view = BidAnnotation(
            uid="view",
            annotation_type="namedview",
            page_uid=self.page,
            position=[0, 0, 10, 10],
            properties={"Text": "View"},
        )
        self.link = BidAnnotation(
            uid="link",
            annotation_type="hotlink",
            page_uid=self.page,
            position=[20, 20],
            properties={"BidPageViewUID": "view"},
        )
        f.data.annotations = [self.view, self.link]
        f.refresh()

    def link_targets(self):
        return [
            (a.uid, a.properties["BidPageViewUID"])
            for a in self.fixture.data.annotations
            if a.annotation_type == "hotlink"
        ]

    def test_local_delete_history_hotlink_follows_restored_named_view(self):
        data = self.fixture.data
        self.window._on_elements_deleted(["link"])
        self.window._on_elements_deleted(["view"])
        self.assertEqual(data.annotations, [])
        for cycle in range(2):
            self.writer.next_uids = [f"view-{cycle}"]
            self.history.undo()
            self.assertEqual([a.uid for a in data.annotations], [f"view-{cycle}"])
            self.writer.next_uids = [f"link-{cycle}"]
            self.history.undo()
            self.assertEqual(self.link_targets(), [(f"link-{cycle}", f"view-{cycle}")])
            self.history.redo()
            self.history.redo()
            self.assertEqual(data.annotations, [])
        self.warning.assert_not_called()

    def test_local_delete_history_refuses_hotlink_for_unrelated_reused_uid(self):
        data = self.fixture.data
        self.window._on_elements_deleted(["link"])
        data.annotations.remove(self.view)
        self.history.invalidate_deleted_annotation_lifetimes(
            self.fixture.bid_ref.file_path,
            self.fixture.bid_ref.bid_uid,
            {(self.page, "namedview", "view")},
            "another-window",
        )
        data.annotations.append(
            BidAnnotation(
                uid="view",
                annotation_type="namedview",
                page_uid=self.page,
                position=[0, 0, 10, 10],
                properties={"Text": "Unrelated"},
            )
        )
        inserts_before = len(self.writer.insert_calls)
        self.history.undo()
        self.warning.assert_called_once()
        self.assertIn("Named View", self.warning.call_args.args[2])
        self.assertEqual(len(self.writer.insert_calls), inserts_before)
        self.assertEqual(self.link_targets(), [])
        self.assertTrue(self.history.can_undo())

    def place_link_through_dialog(self, target):
        from types import SimpleNamespace
        from PySide6 import QtWidgets
        from ost_visualizer.presentation.windows.components import (
            window as window_module,
        )

        class AcceptingDialog:
            def __init__(self, *_args, **_kwargs):
                pass

            def exec(self):
                return QtWidgets.QDialog.DialogCode.Accepted

            def result_data(self):
                return SimpleNamespace(create_new=False, named_view_uid=target)

        self.window._annotation_placement_enabled = lambda: True
        with (
            patch.object(window_module, "SelectNamedViewDialog", AcceptingDialog),
            patch.object(window_module, "isValid", return_value=True),
            patch.object(window_module, "delete_later_if_valid"),
        ):
            self.window._on_hotlink_placement_requested([30.0, 30.0], self.page)

    def test_local_placement_redo_hotlink_follows_named_view_restored_by_cascade(
        self,
    ):
        from ost_visualizer.presentation.windows.components import (
            window as window_module,
        )

        data = self.fixture.data
        data.annotations.remove(self.link)
        self.fixture.refresh()
        self.writer.next_uids = ["placed"]
        self.place_link_through_dialog("view")
        self.assertEqual(self.link_targets(), [("placed", "view")])
        self.window._linked_hotlink_resolver = lambda uids: [
            a
            for a in data.annotations
            if a.annotation_type == "hotlink" and a.properties["BidPageViewUID"] in uids
        ]
        with patch.object(window_module, "confirm", return_value=True) as confirm:
            self.window._on_elements_deleted(["view"])
        confirm.assert_called_once()
        self.assertEqual(data.annotations, [])
        # The cascade restore inserts the Named View first and its link second.
        allocated = ["view-2", "link-2"]
        record_insert = self.writer.insert_annotations

        def allocate(*args, **kwargs):
            record_insert(*args, **kwargs)
            return [allocated.pop(0) for _ in args[2]]

        self.writer.insert_annotations = allocate
        self.history.undo()
        self.assertEqual(self.link_targets(), [("link-2", "view-2")])
        # Undo the placement, then redo it: it must follow the restored view.
        self.history.undo()
        self.assertEqual(self.link_targets(), [])
        self.writer.insert_annotations = record_insert
        self.writer.next_uids = ["placed-2"]
        self.history.redo()
        self.assertEqual(
            self.writer.insert_calls[-1][2][0].properties,
            {"BidPageViewUID": "view-2"},
        )
        self.assertEqual(self.link_targets(), [("placed-2", "view-2")])
        self.warning.assert_not_called()

    def restore_view_through_sql_undo(self, new_uid):
        data = self.fixture.data
        self.history.undo()
        _db, payload, _options, callback = self.write.queued_pastes[-1]
        self.assertEqual(
            [spec.annotation_type for spec in payload.annotation_specs], ["namedview"]
        )
        data.annotations.append(
            BidAnnotation(
                uid=new_uid,
                annotation_type="namedview",
                page_uid=self.page,
                position=[0, 0, 10, 10],
                properties={"Text": "View"},
            )
        )
        callback(HotlinkViewLifetimeHistoryTests.sql_result(payload, [new_uid]))

    def test_sql_delete_history_hotlink_follows_restored_named_view(self):
        data = self.fixture.data
        bid = self.fixture.bid_ref
        for item in (self.link, self.view):
            data.annotations.remove(item)
            self.window._push_sql_annotation_delete_history(bid, [item])
        self.restore_view_through_sql_undo("view-2")
        self.history.undo()
        payload = self.write.queued_pastes[-1][1]
        self.assertEqual(
            [spec.annotation_type for spec in payload.annotation_specs], ["hotlink"]
        )
        self.assertEqual(
            payload.annotation_specs[0].properties["BidPageViewUID"], "view-2"
        )
        self.warning.assert_not_called()

    def test_sql_insert_history_redo_hotlink_follows_restored_named_view(self):
        from ost_visualizer.application.dtos.collaboration_dtos import (
            PlanItemsPastePayload,
        )
        from ost_visualizer.application.dtos.collaboration_resource_catalog import (
            annotation_resource_id,
        )
        from ost_visualizer.application.dtos.insert_annotation_spec_dto import (
            InsertAnnotationSpec,
        )

        data = self.fixture.data
        bid = self.fixture.bid_ref
        source = annotation_resource_id("hotlink", "placed")
        payload = PlanItemsPastePayload(
            source_bid_uid=str(bid.bid_uid),
            destination_bid_uid=str(bid.bid_uid),
            annotation_source_uids=(source,),
            annotation_specs=(
                InsertAnnotationSpec(
                    page_uid=self.page,
                    annotation_type="hotlink",
                    position=[30.0, 30.0],
                    color="#ff0000",
                    width=1.0,
                    properties={"BidPageViewUID": "view"},
                ),
            ),
        )
        placed = BidAnnotation(
            uid="placed",
            annotation_type="hotlink",
            page_uid=self.page,
            position=[30.0, 30.0],
            properties={"BidPageViewUID": "view"},
        )
        data.annotations.append(placed)
        self.window._push_sql_annotation_insert_history(
            bid, payload, {source: "placed"}
        )
        data.annotations.remove(self.view)
        self.window._push_sql_annotation_delete_history(bid, [self.view])
        self.restore_view_through_sql_undo("view-2")
        # Undo the placement (a delete), then redo it onto the restored view.
        self.history.undo()
        data.annotations.remove(placed)
        self.write.queued_deletes[-1][-1](HotlinkViewLifetimeHistoryTests.sql_result())
        pastes_before = len(self.write.queued_pastes)
        self.history.redo()
        self.assertEqual(len(self.write.queued_pastes), pastes_before + 1)
        spec = self.write.queued_pastes[-1][1].annotation_specs[0]
        self.assertEqual(spec.properties["BidPageViewUID"], "view-2")
        self.warning.assert_not_called()

    def test_local_paste_redo_hotlink_follows_named_view_restored_by_cascade(self):
        from ost_visualizer.presentation.services.selection_clipboard_service import (
            SelectionClipboardService,
        )
        from ost_visualizer.presentation.windows.components import (
            window as window_module,
        )

        data = self.fixture.data
        bid = self.fixture.bid_ref
        self.window._annotation_placement_enabled = lambda: True
        self.window._annotation_clipboard_svc = SelectionClipboardService()
        self.window._annotation_clipboard_svc.copy(
            [],
            [self.link],
            source_bid_uid=bid.bid_uid,
            source_file_path=bid.file_path,
        )
        self.writer.next_uids = ["pasted"]
        self.window._on_paste_requested()
        self.assertEqual(
            sorted(self.link_targets()), [("link", "view"), ("pasted", "view")]
        )
        self.window._linked_hotlink_resolver = lambda uids: [
            a
            for a in data.annotations
            if a.annotation_type == "hotlink" and a.properties["BidPageViewUID"] in uids
        ]
        with patch.object(window_module, "confirm", return_value=True):
            self.window._on_elements_deleted(["view"])
        self.assertEqual(data.annotations, [])
        allocated = ["view-2", "link-2", "pasted-2"]
        record_insert = self.writer.insert_annotations

        def allocate(*args, **kwargs):
            record_insert(*args, **kwargs)
            return [allocated.pop(0) for _ in args[2]]

        self.writer.insert_annotations = allocate
        self.history.undo()
        self.assertEqual(
            sorted(self.link_targets()), [("link-2", "view-2"), ("pasted-2", "view-2")]
        )
        self.history.undo()
        self.assertEqual(self.link_targets(), [("link-2", "view-2")])
        self.writer.insert_annotations = record_insert
        self.writer.next_uids = ["pasted-3"]
        self.history.redo()
        self.assertEqual(
            sorted(self.link_targets()), [("link-2", "view-2"), ("pasted-3", "view-2")]
        )
        self.warning.assert_not_called()


class HotlinkViewDependencyHelperTests(unittest.TestCase):
    """capture_/resolve_hotlink_view_targets: which Hot Links retain a Named
    View dependency, and when a restore may follow it."""

    BID = action_fixtures.FakeUiState().get_selected_bid_ref()

    def data(self, *annotations, bid=None):
        from types import SimpleNamespace

        return SimpleNamespace(
            get_all_annotations=lambda: list(annotations),
            get_current_bid_ref=lambda: bid or self.BID,
        )

    @staticmethod
    def view(uid, page="p1"):
        return BidAnnotation(
            uid=uid,
            annotation_type="namedview",
            page_uid=page,
            position=[0, 0, 10, 10],
        )

    @staticmethod
    def link(uid, target, kind="hotlink"):
        return BidAnnotation(
            uid=uid,
            annotation_type=kind,
            page_uid="p1",
            position=[1, 1],
            properties={"BidPageViewUID": target},
        )

    def capture(self, data, items, batch=()):
        from ost_visualizer.presentation.services.annotation_history import (
            capture_hotlink_view_dependencies,
        )

        return capture_hotlink_view_dependencies(data, self.BID, items, batch)

    def test_capture_retains_one_shared_target_per_live_external_named_view(self):
        data = self.data(self.view("5"), self.view("6", "p2"))
        items = [self.link("a", "5"), self.link("b", "5"), self.link("c", "6")]
        first, second, third = self.capture(data, items)
        self.assertIs(first, second)
        self.assertEqual(
            (first.bid_ref, first.page_uid, first.annotation_type, first.uid),
            (self.BID, "p1", "namedview", "5"),
        )
        self.assertTrue(first.available)
        self.assertEqual(
            (third.page_uid, third.annotation_type, third.uid),
            ("p2", "namedview", "6"),
        )
        from ost_visualizer.presentation.services.annotation_history import (
            retained_hotlink_view_targets,
        )

        self.assertEqual(
            retained_hotlink_view_targets((first, None, second, third)), (first, third)
        )

    def test_capture_skips_everything_that_is_not_an_external_live_view_link(self):
        data = self.data(self.view("5"), self.view("7"))
        items = [
            self.link("same-batch", "7"),
            self.link("missing-view", "99"),
            self.link("no-target", None),
            self.link("zero-target", "0"),
            self.link("empty-target", ""),
            self.link("not-a-hotlink", "5", kind="rect"),
        ]
        self.assertEqual(self.capture(data, items, batch={"7"}), (None,) * 6)

    def test_resolve_points_links_at_the_current_uid_without_mutating_the_spec(self):
        from ost_visualizer.presentation.services.annotation_history import (
            resolve_hotlink_view_targets,
        )

        data = self.data(self.view("5"))
        original = self.link("a", "5")
        other = self.link("b", "5", kind="rect")
        dependencies = self.capture(data, [original])
        (target,) = dependencies
        # An accepted restore map rebinds the target to the Named View's new uid.
        target.uid = "10"
        data = self.data(self.view("10"))
        resolved = resolve_hotlink_view_targets(data, [original, other], (target, None))
        self.assertEqual(resolved[0].properties["BidPageViewUID"], "10")
        self.assertEqual(original.properties["BidPageViewUID"], "5")
        self.assertIs(resolved[1], other)
        self.assertEqual(resolve_hotlink_view_targets(data, [original], ()), [original])

    def test_resolve_refuses_instead_of_guessing(self):
        from ost_visualizer.domain.entities.identity_refs import BidRef
        from ost_visualizer.presentation.services.annotation_history import (
            AnnotationHistoryDependencyError,
            resolve_hotlink_view_targets,
        )

        item = self.link("a", "5")
        (target,) = self.capture(self.data(self.view("5")), [item])

        def resolve(data):
            return resolve_hotlink_view_targets(data, [item], (target,))

        # Control: live, available, same Bid and Page resolves.
        self.assertEqual(resolve(self.data(self.view("5")))[0].uid, "a")
        with self.assertRaises(AnnotationHistoryDependencyError):
            resolve(self.data())
        with self.assertRaises(AnnotationHistoryDependencyError):
            resolve(self.data(self.view("5", "p2")))
        with self.assertRaises(AnnotationHistoryDependencyError):
            resolve(self.data(self.view("5"), bid=BidRef("other.mdb", "9")))
        target.available = False
        with self.assertRaises(AnnotationHistoryDependencyError):
            resolve(self.data(self.view("5")))

    def test_binding_from_specs_excludes_named_views_of_its_own_batch(self):
        from ost_visualizer.application.dtos.collaboration_resource_catalog import (
            annotation_resource_id,
        )
        from ost_visualizer.application.dtos.insert_annotation_spec_dto import (
            InsertAnnotationSpec,
        )
        from ost_visualizer.presentation.services.annotation_write_coordinator import (
            AnnotationWriteCoordinator,
        )

        coordinator = AnnotationWriteCoordinator(None, self.data(self.view("5")), None)
        specs = [
            InsertAnnotationSpec(
                page_uid="p1",
                annotation_type="hotlink",
                position=[1.0, 1.0],
                color="#ff0000",
                width=1.0,
                properties={"BidPageViewUID": "5"},
            )
        ]

        def dependencies(source_uids):
            binding = coordinator.history_from_specs(
                self.BID,
                specs,
                ["new"],
                None,
                captured_scales={},
                source_uids=source_uids,
            )
            return binding.view_dependencies, binding.history_targets()

        # Control: the live view 5 is an external dependency of the new link.
        (external,), targets = dependencies(())
        self.assertEqual((external.annotation_type, external.uid), ("namedview", "5"))
        self.assertEqual(len(targets), 2)
        # The same view named as a source of the batch is remapped by the write.
        sources = [
            annotation_resource_id("namedview", "5"),
            annotation_resource_id("hotlink", "src"),
        ]
        self.assertEqual(dependencies(sources)[0], (None,))
        self.assertEqual(len(dependencies(sources)[1]), 1)
