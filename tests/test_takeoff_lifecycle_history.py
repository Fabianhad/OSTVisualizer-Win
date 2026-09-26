import unittest
from dataclasses import replace
from itertools import product
from tests import test_plan_property_history_identity as fixtures
from tests import test_plan_view_action_handler as action_fixtures
from ost_visualizer.application.dtos.collaboration_dtos import (
    PlanItemsPastePayload,
    AuthoritativeMutationResult,
)
from ost_visualizer.application.dtos.insert_takeoff_spec_dto import InsertTakeoffSpec


class TakeoffLifecycleHistoryTests(unittest.TestCase):
    def test_history_projection_rejects_destroyed_native_plan_owner(self):
        from PySide6.QtWidgets import QApplication, QWidget
        from shiboken6 import delete

        app = QApplication.instance() or QApplication([])
        handler, _data, _write, _undo = (
            fixtures.PlanPropertyHistoryIdentityTests().make_handler()
        )
        plan = QWidget()
        plan._is_cleaning_up = False
        plan.current_page_uid = "p1"
        handler._plan_view = plan
        bid_ref = handler._ui_state.get_selected_bid_ref()
        self.assertTrue(handler._plan_context_is_current(bid_ref, ("p1",)))
        plan._is_cleaning_up = True
        self.assertFalse(handler._plan_context_is_current(bid_ref, ("p1",)))
        plan._is_cleaning_up = False
        delete(plan)
        self.assertFalse(handler._plan_context_is_current(bid_ref, ("p1",)))

    def test_paste_completion_does_not_project_into_cleaned_plan(self):
        fixture = fixtures.PlanPropertyHistoryIdentityTests()
        handler, _data, write, _undo = fixture.make_handler()
        payload = PlanItemsPastePayload(
            source_bid_uid="7",
            destination_bid_uid="7",
            takeoff_source_uids=("source",),
            takeoff_specs=(InsertTakeoffSpec("c1", "p1", "0", [3, 4]),),
        )
        handler._queue_sql_plan_items_paste_payload(
            handler._ui_state.get_selected_bid_ref(), "p1", payload, ()
        )
        handler._plan_view._is_cleaning_up = True
        write.queued_pastes[-1][-1](
            fixture.committed(
                AuthoritativeMutationResult(
                    created_uid_maps=(("takeoffs", (("source", "persisted"),)),)
                )
            )
        )
        self.assertEqual(handler._plan_view.selected, set())

    def test_cross_bid_paste_redo_reuses_created_condition(self):
        fixture = action_fixtures.PlanViewActionHandlerTests()
        write = action_fixtures.FakeWriteService()
        handler = fixture._paste_handler(write=write)
        handler._clipboard_svc = action_fixtures.FakeClipboard(
            [fixture._copied_takeoff()], source_bid_uid="6"
        )
        handler.on_paste_requested()
        handler._undo_svc.undo()
        handler._undo_svc.redo()
        self.assertEqual(len(write.condition_duplicate_calls), 1)
        self.assertEqual(write.calls[-1][2][0].condition_uid, "new-c1")

    def test_queued_paste_completion_cannot_select_into_replacement_page(self):
        fixture = fixtures.PlanPropertyHistoryIdentityTests()
        handler, data, write, undo = fixture.make_handler()
        bid_ref = handler._ui_state.get_selected_bid_ref()
        payload = PlanItemsPastePayload(
            source_bid_uid="7",
            destination_bid_uid="7",
            takeoff_source_uids=("source",),
            takeoff_specs=(InsertTakeoffSpec("c1", "p1", "0", [3, 4]),),
        )
        handler._queue_sql_plan_items_paste_payload(bid_ref, "p1", payload, ())
        from copy import deepcopy

        data.pages["p1"] = deepcopy(data.pages["p1"])
        callback = write.queued_pastes[-1][-1]
        callback(
            fixture.committed(
                AuthoritativeMutationResult(
                    created_uid_maps=(("takeoffs", (("source", "persisted"),)),)
                )
            )
        )
        self.assertEqual(handler._plan_view.selected, set())
        self.assertFalse(undo.can_undo())

    def test_child_paste_redo_follows_restored_parent_and_current_scale(self):
        fixture = fixtures.PlanPropertyHistoryIdentityTests()
        for queued, source_uid in product((False, True), ("source", "parent")):
            with self.subTest(queued=queued, source_uid=source_uid):
                handler, data, write, undo = fixture.make_handler()
                bid_ref = handler._ui_state.get_selected_bid_ref()
                data.pages["p1"].scale_factor1 = 0.125
                data.pages["p1"].scale_factor2 = 12
                payload = PlanItemsPastePayload(
                    source_bid_uid="7",
                    destination_bid_uid="7",
                    takeoff_source_uids=(source_uid,),
                    takeoff_external_parent_sources=(source_uid,),
                    takeoff_specs=(
                        InsertTakeoffSpec(
                            "c1",
                            "p1",
                            "area-b",
                            [96, 96, 192, 96, 192, 192],
                            parent_uid="parent",
                        ),
                    ),
                )
                if queued:
                    handler._push_sql_paste_history(
                        bid_ref, payload, {source_uid: "child"}, {}
                    )
                else:
                    handler._push_mdb_paste_history(
                        bid_ref, payload, (), {source_uid: "child"}, {}
                    )
                write.sql_collaboration_mutations = queued
                handler.on_elements_deleted(["parent"])
                if queued:
                    data.takeoffs.clear()
                    write.queued_deletes[-1][-1](fixture.committed())
                write.uid_batches = [["restored-parent"], ["restored-child"]]
                undo.undo()
                if queued:
                    database, restore_payload, _options, callback = write.queued_pastes[
                        -1
                    ]
                    result = write.execute_plan_items_paste_local(
                        database, restore_payload
                    )
                    handler._project_mdb_plan_items_paste(
                        bid_ref, restore_payload, result
                    )
                    callback(fixture.committed(result.authoritative_result))
                undo.undo()
                if queued:
                    data.takeoffs.pop("restored-child")
                    write.queued_deletes[-1][-1](fixture.committed())
                data.pages["p1"].scale_factor1 = 0.1875
                if not queued:
                    write.uid_batches = [["redone-child"]]
                undo.redo()
                if queued:
                    replay = write.queued_pastes[-1][1].takeoff_specs[0]
                    self.assertEqual(replay.parent_uid, "restored-parent")
                    self.assertEqual(replay.position, [64, 64, 128, 64, 128, 128])
                else:
                    self.assertEqual(
                        data.takeoffs["redone-child"].parent_uid, "restored-parent"
                    )
                    self.assertEqual(
                        data.takeoffs["redone-child"].position,
                        [64, 64, 128, 64, 128, 128],
                    )

    def complete_geometry(self, fixture, data, write):
        _database, _bid, updates, callback = write.queued_geometry[-1]
        for uid, position in updates["takeoff_positions"]:
            data.takeoffs[uid].position = list(position)
        for uid, rotation in updates["takeoff_rotations"]:
            data.takeoffs[uid].rotation = rotation
        callback(fixture.committed())

    def test_geometry_history_follows_delete_restore_mapping_not_reused_uid(self):
        fixture = fixtures.PlanPropertyHistoryIdentityTests()
        for queued in (False, True):
            for kind in ("move", "rotation", "group"):
                with self.subTest(queued=queued, kind=kind):
                    handler, data, write, undo = fixture.make_handler()
                    data.takeoffs.pop("child")
                    before = replace(
                        data.takeoffs["parent"],
                        position=list(data.takeoffs["parent"].position),
                    )
                    after = [value + 2 for value in before.position]
                    write.sql_collaboration_mutations = queued
                    if kind == "move":
                        handler.on_positions_flushed(
                            [("parent", before.position, after)], []
                        )
                    elif kind == "rotation":
                        handler.on_rotations_flushed([("parent", 0, 0.5)])
                    else:
                        handler.on_group_rotation_flushed(
                            [("parent", before.position, after)],
                            [],
                            [("parent", 0, 0.5)],
                        )
                    if queued:
                        self.complete_geometry(fixture, data, write)
                    handler.on_elements_deleted(["parent"])
                    if queued:
                        data.takeoffs.pop("parent")
                        write.queued_deletes[-1][-1](fixture.committed())
                    write.uid_batches = [["restored"]]
                    undo.undo()
                    if queued:
                        database, payload, _options, callback = write.queued_pastes[-1]
                        result = write.execute_plan_items_paste_local(database, payload)
                        handler._project_mdb_plan_items_paste(
                            handler._ui_state.get_selected_bid_ref(), payload, result
                        )
                        callback(fixture.committed(result.authoritative_result))
                    data.takeoffs["parent"] = replace(
                        before, position=[100, 100], rotation=9
                    )
                    undo.undo()
                    if queued:
                        self.complete_geometry(fixture, data, write)
                    self.assertEqual(data.takeoffs["parent"].position, [100, 100])
                    self.assertEqual(data.takeoffs["parent"].rotation, 9)
                    self.assertEqual(
                        data.takeoffs["restored"].position, before.position
                    )
                    self.assertEqual(data.takeoffs["restored"].rotation, 0)

    def test_sql_geometry_history_adapts_to_current_page_scale(self):
        fixture = fixtures.PlanPropertyHistoryIdentityTests()
        handler, data, write, undo = fixture.make_handler()
        data.pages["p1"].scale_factor1 = 0.125
        data.pages["p1"].scale_factor2 = 12
        write.sql_collaboration_mutations = True
        before = [0, 0, 96, 0, 96, 96]
        handler.on_positions_flushed([("parent", before, [0, 0, 120, 0, 120, 120])], [])
        self.complete_geometry(fixture, data, write)
        data.pages["p1"].scale_factor1 = 0.1875
        undo.undo()
        self.assertEqual(
            write.queued_geometry[-1][2]["takeoff_positions"],
            [("parent", [0, 0, 64, 0, 64, 64])],
        )
