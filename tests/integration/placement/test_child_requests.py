import unittest
from dataclasses import replace
from ost_visualizer.application.dtos.collaboration_dtos import (
    DatabaseMutationResult,
    MutationOutcomeStatus,
)
from ost_visualizer.domain.entities.condition import Condition
from ost_visualizer.domain.entities.takeoff import Takeoff
from ost_visualizer.presentation.services.selection_clipboard_service import (
    SelectionClipboardService,
)
import tests.integration.history.test_property_lifetimes as history_fixtures
import tests.presentation.components.plan_view.components.test_placement_mode as placement_fixtures


class TakeoffLifecycleRequestTests(unittest.TestCase):
    def test_cross_bid_child_paste_uses_one_atomic_mutation(self):
        from ost_visualizer.application.dtos.collaboration_dtos import (
            MutationExecutionResult,
        )

        handler, _data, write, undo = (
            history_fixtures.PlanPropertyHistoryIdentityTests().make_handler()
        )
        handler._clipboard_svc = SelectionClipboardService()
        handler._clipboard_svc.copy([], source_bid_uid="6", source_file_path="bid.mdb")
        submitted = []
        write.execute_plan_items_paste_local = lambda _database, payload, **_options: (
            submitted.append(payload)
            or MutationExecutionResult(
                outcome_status=MutationOutcomeStatus.FAILED_BEFORE_COMMIT
            )
        )
        handler.on_paste_backouts_placed(
            [
                {
                    "condition_uid": "c1",
                    "page_uid": "p1",
                    "position": [1, 1, 2, 1, 2, 2],
                    "parent_uid": "parent",
                    "rotation": 0,
                    "is_negative": False,
                    "extras": {},
                }
            ],
            "6",
        )
        self.assertEqual(len(submitted), 1)
        self.assertEqual(write.condition_duplicate_calls, [])
        self.assertFalse(undo.can_undo())

    def test_nested_child_placement_persists_remapped_hierarchy(self):
        for sql in (False, True):
            with self.subTest(sql=sql):
                handler, data, write, _undo = (
                    history_fixtures.PlanPropertyHistoryIdentityTests().make_handler()
                )
                handler._clipboard_svc = SelectionClipboardService()
                handler._clipboard_svc.copy(
                    [], source_bid_uid="7", source_file_path="bid.mdb"
                )
                write.sql_collaboration_mutations = sql
                placements = [
                    {
                        "source_uid": "source-root",
                        "condition_uid": "c1",
                        "page_uid": "p1",
                        "position": [1, 1, 9, 1, 9, 9],
                        "parent_uid": "parent",
                        "parent_is_internal": False,
                        "rotation": 0,
                        "is_negative": False,
                        "extras": {},
                    },
                    {
                        "source_uid": "source-child",
                        "condition_uid": "c1",
                        "page_uid": "p1",
                        "position": [2, 2, 3, 2, 3, 3],
                        "parent_uid": "source-root",
                        "parent_is_internal": True,
                        "rotation": 0,
                        "is_negative": False,
                        "extras": {},
                    },
                ]
                write.uid_batches = [["new-root"], ["new-child"]]
                handler.on_paste_backouts_placed(placements, "7")
                if sql:
                    _database, payload, _options, _callback = write.queued_pastes[-1]
                    self.assertEqual(
                        payload.takeoff_source_uids, ("source-root", "source-child")
                    )
                    self.assertEqual(
                        payload.takeoff_external_parent_sources, ("source-root",)
                    )
                else:
                    self.assertEqual(data.takeoffs["new-root"].parent_uid, "parent")
                    self.assertEqual(data.takeoffs["new-child"].parent_uid, "new-root")

    @classmethod
    def setUpClass(cls):
        placement_fixtures.TakeoffLifecyclePlacementTests.setUpClass()

    def test_mixed_paste_validates_external_attachment_footprint_before_submission(
        self,
    ):
        handler, data, write, _undo = (
            history_fixtures.PlanPropertyHistoryIdentityTests().make_handler()
        )
        view = placement_fixtures.TakeoffLifecyclePlacementTests().harness(
            Condition.TYPE_AREA, (0, 0), (1, 1), backout=True
        )
        condition = Condition(
            uid="attachment", condition_type=Condition.TYPE_ATTACHMENT, width=4, depth=4
        )
        view._current_conditions[condition.uid] = condition
        data.conditions[condition.uid] = condition
        handler._clipboard_svc = SelectionClipboardService()
        handler._clipboard_svc.copy([], source_bid_uid="7", source_file_path="bid.mdb")
        handler._plan_view.resolve_pasted_child_parents = (
            lambda *args: view.resolve_pasted_child_parents(*args)
        )
        handler._paste_translation = lambda *_: (0, 0, None)
        count = Takeoff(
            uid="count", condition_uid="c1", page_uid="p1", position=[20, 20]
        )
        attachment = Takeoff(
            uid="point",
            condition_uid="attachment",
            page_uid="p1",
            parent_uid="parent",
            position=[9, 9],
        )
        prepared = handler._prepare_plan_items_paste(
            handler._ui_state.get_selected_bid_ref(),
            "p1",
            "0",
            [count],
            [attachment],
            [],
        )
        self.assertIsNone(prepared)
        self.assertEqual(write.calls, [])

    def test_deleting_any_ancestor_includes_complete_descendant_graph(self):
        for selected, expected in (
            ("parent", {"parent", "child", "grandchild"}),
            ("child", {"child", "grandchild"}),
        ):
            with self.subTest(selected=selected):
                handler, data, write, _undo = (
                    history_fixtures.PlanPropertyHistoryIdentityTests().make_handler()
                )
                data.takeoffs["grandchild"] = replace(
                    data.takeoffs["child"], uid="grandchild", parent_uid="child"
                )
                write.sql_collaboration_mutations = True
                handler.on_elements_deleted([selected])
                self.assertEqual(set(write.queued_deletes[-1][2]), expected)

    def test_copy_parent_captures_detached_descendant_snapshot(self):
        handler, data, _write, _undo = (
            history_fixtures.PlanPropertyHistoryIdentityTests().make_handler()
        )
        handler._clipboard_svc = SelectionClipboardService()
        data.conditions["attachment"] = Condition(
            uid="attachment", condition_type=Condition.TYPE_ATTACHMENT
        )
        data.takeoffs["attachment"] = Takeoff(
            uid="attachment",
            condition_uid="attachment",
            page_uid="p1",
            parent_uid="parent",
            position=[5, 5],
        )
        handler.on_copy_requested(["parent"])
        self.assertEqual(
            {item.uid for item in handler._clipboard_svc.items},
            {"parent", "child", "attachment"},
        )
        data.takeoffs["child"].position[0] = 99
        copied = {item.uid: item for item in handler._clipboard_svc.items}
        self.assertEqual(copied["child"].position[0], 1)
