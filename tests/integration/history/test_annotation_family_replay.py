import math
import unittest
from ost_visualizer.domain.entities.annotation import BidAnnotation
from ost_visualizer.domain.services.page_scale_transform import (
    rescale_annotation_position_between_page_scales,
)
from tests.integration.annotations.family_support import (
    AnnotationFamilyGeometry as _family_support_AnnotationFamilyGeometry,
)


class AnnotationFamilyHistoryTests(unittest.TestCase):
    def test_every_family_replays_after_restore_uid_reuse_and_scale(self):
        import tests.integration.history.test_annotation_lifetimes as fixtures
        from ost_visualizer.presentation.utils.annotation_paste import (
            translate_annotation_position,
        )

        for sql in (False, True):
            for (
                kind,
                position,
            ) in _family_support_AnnotationFamilyGeometry.POSITIONS.items():
                with self.subTest(sql=sql, kind=kind):
                    fixture = fixtures.TextAnnotationHistoryTests()
                    handler, data, writer, write, undo = fixture.make_handler(sql)
                    original = data.annotations[0]
                    original.annotation_type = kind
                    original.position = list(position)
                    handler._plan_view.annotation_key_map = {("a1", kind): "a1"}
                    after = translate_annotation_position(original, 1 / 64, 0.0)
                    handler.on_positions_flushed(
                        [], [("a1", kind, list(position), after)]
                    )
                    if sql:
                        fixture.complete_edit("position", data, write)
                    self.assertEqual(original.position, after)
                    handler.on_elements_deleted(["a1"])
                    if sql:
                        data.remove_annotations_by_keys([("a1", kind)])
                        write.queued_deletes[-1][-1](fixture.committed())
                    self.assertEqual(data.annotations, [])
                    for cycle in range(2):
                        writer.next_uids = [f"restored-{cycle}"]
                        undo.undo()
                        if sql:
                            db, payload, _options, callback = write.queued_pastes[-1]
                            result = write.execute_plan_items_paste_local(db, payload)
                            handler._project_mdb_plan_items_paste(
                                fixtures.action_fixtures.FakeUiState().get_selected_bid_ref(),
                                payload,
                                result,
                            )
                            callback(result)
                        restored = data.annotations[0]
                        self.assertEqual(restored.uid, f"restored-{cycle}")
                        reused = BidAnnotation(
                            "a1", kind, page_uid="p1", position=[999.0, 999.0]
                        )
                        data.annotations.append(reused)
                        data.pages["p1"].scale_factor2 = 2.0
                        undo.undo()
                        if sql:
                            fixture.complete_edit("position", data, write)
                        expected = rescale_annotation_position_between_page_scales(
                            kind, position, (1, 1), (1, 2)
                        )
                        self.assertEqual(restored.position, expected)
                        self.assertEqual(reused.position, [999.0, 999.0])
                        undo.redo()
                        if sql:
                            fixture.complete_edit("position", data, write)
                        self.assertEqual(
                            restored.position,
                            rescale_annotation_position_between_page_scales(
                                kind, after, (1, 1), (1, 2)
                            ),
                        )
                        undo.redo()
                        if sql:
                            data.remove_annotations_by_keys([(restored.uid, kind)])
                            write.queued_deletes[-1][-1](fixture.committed())
                        self.assertEqual(data.annotations, [reused])
                        data.annotations.clear()
                        data.pages["p1"].scale_factor2 = 1.0

    def test_family_scoped_late_sql_completion_does_not_repopulate_history(self):
        import tests.integration.history.test_annotation_lifetimes as fixtures

        for (
            kind,
            position,
        ) in _family_support_AnnotationFamilyGeometry.POSITIONS.items():
            with self.subTest(kind=kind):
                fixture = fixtures.TextAnnotationHistoryTests()
                handler, data, writer, write, undo = fixture.make_handler(True)
                original = data.annotations[0]
                original.annotation_type = kind
                original.position = list(position)
                handler._plan_view.annotation_key_map = {("a1", kind): "a1"}
                after = list(position)
                after[0] += 1.0
                handler.on_positions_flushed([], [("a1", kind, list(position), after)])
                undo.clear()
                fixture.complete_edit("position", data, write)
                self.assertFalse(undo.can_undo())


class MixedAnnotationFailureTests(unittest.TestCase):
    def test_failed_restore_does_not_project_early_named_views(self):
        import tests.integration.history.test_annotation_lifetimes as fixtures

        fixture = fixtures.TextAnnotationHistoryTests()
        handler, data, writer, write, undo = fixture.make_handler()
        data.annotations.clear()
        saved = [
            BidAnnotation(
                "n",
                "namedview",
                page_uid="p1",
                position=[0.0, 0.0, 10.0, 10.0],
                properties={"Text": "View"},
            ),
            BidAnnotation(
                "d", "dimension", page_uid="p1", position=[0.0, 0.0, 10.0, 0.0]
            ),
        ]
        original_insert = writer.insert_annotations

        def fail_dimension(path, bid, specs, *args, **options):
            if any(spec.annotation_type == "dimension" for spec in specs):
                return []
            return original_insert(path, bid, specs, *args, **options)

        writer.insert_annotations = fail_dimension
        restored = handler._annotation_writes.insert_saved_annotations(
            fixtures.action_fixtures.FakeUiState().get_selected_bid_ref(),
            saved,
            execute_paste=write.execute_plan_items_paste_local,
        )
        self.assertEqual(restored, [])
        self.assertEqual(data.annotations, [])

    def test_detached_copy_excludes_named_view_and_preserves_existing_link_target(self):
        import tests.presentation.windows.components.test_window as fixtures

        fixture = fixtures.DetachedPageViewManagerLifecycleTests()
        saved = [
            fixtures._named_view_annotation("view", "View"),
            fixtures._hotlink_annotation("link", "view"),
        ]
        window, plan, writer = fixture._make_annotation_clipboard_window(
            saved, undo_service=fixtures.FakeUndoService()
        )
        plan.set_selected_uids({"view", "link"})
        fixtures.DetachedPageViewWindow._on_copy_requested(window, ["view", "link"])
        fixtures.DetachedPageViewWindow._on_paste_requested(window)
        inserted = window._test_project_data.annotations[2:]
        self.assertEqual(len(inserted), 1)
        self.assertTrue(inserted[0].is_hotlink)
        self.assertEqual(inserted[0].hotlink_target_view_uid, "view")


class CrossFamilyReplayTests(unittest.TestCase):
    def test_same_uid_across_families_move_delete_restore_and_replay_remains_typed(
        self,
    ):
        from unittest.mock import patch
        import tests.integration.history.test_annotation_lifetimes as fixtures
        from ost_visualizer.presentation.utils.annotation_paste import (
            translate_annotation_position,
        )

        fixture = fixtures.TextAnnotationHistoryTests()
        handler, data, writer, write, undo = fixture.make_handler()
        originals = [
            BidAnnotation(
                "1",
                kind,
                page_uid="p1",
                position=list(pos),
                properties={"Text": "View"},
            )
            for kind, pos in _family_support_AnnotationFamilyGeometry.POSITIONS.items()
        ]
        data.annotations = originals
        handler._plan_view.annotations = {
            f"{a.annotation_type}:1": a for a in originals
        }
        handler._plan_view.annotation_key_map = {
            (a.uid, a.annotation_type): f"{a.annotation_type}:1" for a in originals
        }
        changes = [
            (
                a.uid,
                a.annotation_type,
                list(a.position),
                translate_annotation_position(a, 1 / 64, -1 / 32),
            )
            for a in originals
        ]
        before = {kind: position for _uid, kind, position, _after in changes}
        after = {kind: position for _uid, kind, _before, position in changes}
        handler.on_positions_flushed([], changes)
        self.assertEqual(
            {a.annotation_type: a.position for a in data.annotations}, after
        )
        handler.on_elements_deleted(list(handler._plan_view.annotations))
        self.assertEqual(data.annotations, [])
        for cycle in range(2):
            with patch.object(
                writer,
                "insert_annotations",
                side_effect=lambda _db, _bid, specs, *args: [
                    f"restored-{cycle}" for _ in specs
                ],
            ):
                undo.undo()
            self.assertEqual(len(data.annotations), len(originals))
            self.assertEqual({a.uid for a in data.annotations}, {f"restored-{cycle}"})
            reused = [
                BidAnnotation(
                    "1", a.annotation_type, page_uid="p1", position=[999.0, 999.0]
                )
                for a in originals
            ]
            data.annotations.extend(reused)
            undo.undo()
            self.assertEqual(
                {
                    a.annotation_type: a.position
                    for a in data.annotations
                    if a.uid != "1"
                },
                before,
            )
            undo.redo()
            self.assertEqual(
                {
                    a.annotation_type: a.position
                    for a in data.annotations
                    if a.uid != "1"
                },
                after,
            )
            self.assertTrue(all(a.position == [999.0, 999.0] for a in reused))
            undo.redo()
            self.assertEqual(data.annotations, reused)
            data.annotations.clear()

    def test_restore_failure_uses_one_application_mutation_and_no_success_event(self):
        import tests.integration.history.test_annotation_lifetimes as fixtures
        import tests.application.services.test_project_write_service as parity

        fixture = fixtures.TextAnnotationHistoryTests()
        handler, data, _writer, _write, _undo = fixture.make_handler()
        data.annotations.clear()
        service = parity.MdbSqlBehaviorParityTests._local_composite_service()
        service._insert_annotations = parity._SequenceUseCase(
            ["new-view"], RuntimeError("second-family failure")
        )
        saved = [
            BidAnnotation("1", "namedview", page_uid="p1", position=[0, 0, 10, 10]),
            BidAnnotation("1", "dimension", page_uid="p1", position=[0, 0, 10, 0]),
        ]
        events = list(handler._event_bus.events)
        result = handler._annotation_writes.insert_saved_annotations(
            fixtures.action_fixtures.FakeUiState().get_selected_bid_ref(),
            saved,
            execute_paste=service.execute_plan_items_paste_local,
        )
        self.assertEqual(result, [])
        self.assertEqual(len(service.mutation_calls), 1)
        self.assertEqual(len(service._insert_annotations.calls), 2)
        self.assertEqual(data.annotations, [])
        self.assertEqual(handler._event_bus.events, events)
        self.assertEqual(service.reload_calls, [])
